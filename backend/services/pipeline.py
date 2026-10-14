"""资料处理流水线：上传后后台异步执行

读文字(M-02) → 语义切块(M-03) → 向量化(M-04) → 存入 Chroma + 分块表(M-05)。

入口：
- process_material_async(material_id): 起后台守护线程跑 process_material（对应「后台慢慢跑，不用等」）
- process_material(material_id, embedder=None): 同步执行（embedder 可注入，便于测试）

后台线程使用独立的 SQLAlchemy 引擎/会话，避免与请求线程共享会话。
"""
import threading
import traceback

from config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.material import Material, MaterialChunk
from services.extractors import extract_text
from services.chunking import chunk_text
from services.vector_store import vector_store
from services.clients import EmbeddingClient


_engine = create_engine(
    Config.DB_URL, future=True, connect_args={"check_same_thread": False}
)
_Session = sessionmaker(bind=_engine, future=True)


def process_material_async(material_id: str):
    t = threading.Thread(target=_run, args=(material_id,), daemon=True)
    t.start()
    return t


def _run(material_id: str):
    """后台线程入口：兜底捕获异常，保证资料状态最终可见（processing → ready/error）。"""
    try:
        process_material(material_id)
    except Exception:
        try:
            with _Session() as s:
                m = s.get(Material, material_id)
                if m:
                    m.status = "error"
                    m.error_message = traceback.format_exc(limit=5)[-500:]
                    s.commit()
        except Exception:
            pass


def process_material(material_id: str, embedder=None):
    """完整处理一份资料。embedder 默认用 EmbeddingClient（阿里云百炼 text-embedding-v4）。"""
    embedder = embedder or EmbeddingClient()
    with _Session() as s:
        m = s.get(Material, material_id)
        if not m:
            return

        pages = extract_text(m.file_path, m.file_type)
        chunks = chunk_text(pages)
        if not chunks:
            m.status = "error"
            m.error_message = "未从文件中提取到任何文字"
            s.commit()
            return

        texts = [c.content for c in chunks]
        embeddings = embedder.embed(texts)

        # 存入 Chroma 向量库
        vector_store.add_chunks(m.id, m.title, m.file_type, chunks, embeddings)

        # 分块表：记录来源元数据（文件名 / 页码 / 块序号）
        for c in chunks:
            s.add(
                MaterialChunk(
                    id=f"{m.id}_{c.chunk_index}",
                    material_id=m.id,
                    chunk_index=c.chunk_index,
                    page_number=c.page_number,
                    content=c.content,
                    token_count=len(c.content),
                )
            )

        total_pages = max((p.page_number for p in pages), default=0)
        m.status = "ready"
        m.chunk_count = len(chunks)
        m.total_pages = total_pages
        m.error_message = None
        s.commit()
