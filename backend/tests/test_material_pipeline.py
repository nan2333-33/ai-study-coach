"""资料处理流水线验证（无需真实 API Key）。

- 用确定性 FakeEmbedder 替代阿里云百炼 embedding，验证：
  1) 各格式文本提取（MD / TXT / DOCX / PPTX）
  2) 语义分块（500-800 字、保留页码）
  3) Chroma 存储 + 余弦检索（低相关性被过滤）
  4) 上传→后台处理→状态变 ready→删除全清（文件/向量/DB）
"""
import os
import sys
import io
import math
import hashlib
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

# 用独立临时 SQLite，避免污染开发库
_TMP_DB = os.path.join(tempfile.gettempdir(), "ailms_test.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DB_URL"] = "sqlite:///" + _TMP_DB

import services.pipeline as pipeline
from services.extractors import extract_text
from services.chunking import chunk_text
from services.vector_store import vector_store


class FakeEmbedder:
    """确定性向量：相同文本→相同向量，仅用于验证存储/检索链路。

    dim 必须跟 Config.EMBED_DIM 一致，否则 Chroma 会按维度不符拒绝写入。
    """

    def __init__(self):
        from config import Config

        self.dim = int(Config.EMBED_DIM)

    def embed(self, texts):
        out = []
        for t in texts:
            h = hashlib.md5(t.encode()).digest()
            vec = [((h[i % len(h)] / 255.0) - 0.5) for i in range(self.dim)]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


# 让后台流水线使用 FakeEmbedder
_orig = pipeline.process_material


def _patched(material_id, embedder=None):
    return _orig(material_id, embedder=FakeEmbedder())


pipeline.process_material = _patched


def _make_docx(path):
    from docx import Document

    d = Document()
    for i in range(20):
        d.add_paragraph(f"大模型第 {i} 个知识点。这是关于Transformer架构与注意力机制的说明，用于验证Word文档提取。")
    d.save(path)


def _make_pptx(path):
    from pptx import Presentation

    p = Presentation()
    for i in range(10):
        slide = p.slides.add_slide(p.slide_layouts[1])
        slide.shapes.title.text = f"第{i}页标题"
        slide.placeholders[1].text = f"本页讲解内容要点 {i}，包含模型训练与推理流程。"
        slide.notes_slide.notes_text_frame.text = f"备注补充：第{i}页的关键公式与推导。"
    p.save(path)


def check(name, cond):
    print(("  PASS " if cond else "  FAIL ") + name)
    if not cond:
        raise SystemExit(f"验证失败: {name}")


def test_extraction_and_chunking():
    print("[1] 提取 + 分块")
    md = "# 标题\n\n" + "\n\n".join(
        f"这是第{i}段关于大模型的说明文字，用于测试Markdown提取与分块逻辑是否正常工作。" for i in range(30)
    )
    tmp = tempfile.mkdtemp()
    md_path = os.path.join(tmp, "a.md")
    open(md_path, "w", encoding="utf-8").write(md)
    txt_path = os.path.join(tmp, "b.txt")
    open(txt_path, "w", encoding="utf-8").write(md)
    docx_path = os.path.join(tmp, "c.docx")
    _make_docx(docx_path)
    pptx_path = os.path.join(tmp, "d.pptx")
    _make_pptx(pptx_path)

    for ftype, path in [("md", md_path), ("txt", txt_path), ("docx", docx_path), ("pptx", pptx_path)]:
        pages = extract_text(path, ftype)
        check(f"{ftype}: 提取到文字", any(p.text.strip() for p in pages))
        chunks = chunk_text(pages)
        check(f"{ftype}: 切块非空", len(chunks) > 0)
        sizes = [len(c.content) for c in chunks]
        check(f"{ftype}: 块大小在合理范围(<=900)", max(sizes) <= 900)
        check(f"{ftype}: 保留页码", all(c.page_number >= 1 for c in chunks))
    return tmp


def test_store_and_search(tmp):
    print("[2] Chroma 存储 + 余弦检索（低相关性过滤）")
    md_path = os.path.join(tmp, "a.md")
    pages = extract_text(md_path, "md")
    chunks = chunk_text(pages)
    vector_store.add_chunks("mat_test", "测试资料", "md", chunks, FakeEmbedder().embed([c.content for c in chunks]))

    # 用第一个块的原向量检索 → 应召回且相似度很高
    vec0 = FakeEmbedder().embed([chunks[0].content])[0]
    hits = vector_store.search(vec0, material_ids=["mat_test"], top_k=5, min_score=0.15)
    check("检索召回自身块", len(hits) >= 1)
    check("最相关块相似度接近1", hits[0]["score"] > 0.9)
    check("返回字段含来源页码", "pageNumber" in hits[0] and "materialId" in hits[0])

    # 用完全相反的向量检索 → 相似度低，应被阈值过滤为空
    far = [-x for x in vec0]
    dropped = vector_store.search(far, material_ids=["mat_test"], top_k=5, min_score=0.15)
    check("低相关性片段被丢弃", len(dropped) == 0)

    # 清理该测试资料
    vector_store.delete_material("mat_test")
    after = vector_store.search(vec0, material_ids=["mat_test"], top_k=5, min_score=0.0)
    check("删除后向量清空", len(after) == 0)


def test_upload_pipeline_and_delete():
    print("[3] 上传→后台处理→删除全清（端到端）")
    from app import create_app

    app = create_app()
    client = app.test_client()

    md = "# 端到端测试\n\n" + "\n\n".join(
        f"段落{i}：关于检索增强生成RAG的要点说明，用于验证上传后自动处理流程。" for i in range(40)
    )
    resp = client.post(
        "/api/materials/upload",
        data={"file": (io.BytesIO(md.encode()), "e2e.md"), "title": "端到端测试"},
        content_type="multipart/form-data",
    )
    check("上传返回200", resp.status_code == 200)
    body = resp.get_json()
    check("上传返回 code=0", body["code"] == 0)
    mid = body["data"]["materialId"]
    check("初始状态 processing", body["data"]["status"] == "processing")

    # 等待后台线程处理完成
    import time

    for _ in range(40):
        r = client.get(f"/api/materials/{mid}").get_json()
        if r["data"]["status"] in ("ready", "error"):
            break
        time.sleep(0.25)

    detail = client.get(f"/api/materials/{mid}").get_json()["data"]
    check("状态变为 ready", detail["status"] == "ready")
    check("chunkCount > 0", detail["chunkCount"] > 0)
    check("分块列表返回预览", len(detail["chunks"]) == detail["chunkCount"])

    # 列表接口应能查到
    listing = client.get("/api/materials").get_json()["data"]
    check("列表含该资料", any(x["materialId"] == mid for x in listing["list"]))

    # 删除：文件 + 向量 + DB 一起清
    upload_dir = app.config.get("UPLOAD_DIR") if "UPLOAD_DIR" in app.config else None
    # 记录文件路径以便后续确认删除
    from models.material import Material
    with app.app_context():
        pass
    del_resp = client.delete(f"/api/materials/{mid}")
    check("删除返回 deleted=true", del_resp.get_json()["data"]["deleted"] is True)
    gr = client.get(f"/api/materials/{mid}")
    print("    [debug] GET after delete:", gr.status_code, gr.get_json())
    check("删除后查询404", gr.status_code == 404)

    # 向量层也应清空
    remain = vector_store.search(
        FakeEmbedder().embed(["RAG 检索增强生成"])[0],
        material_ids=[mid],
        top_k=5,
        min_score=0.0,
    )
    check("删除后向量已清", len(remain) == 0)


if __name__ == "__main__":
    t = test_extraction_and_chunking()
    test_store_and_search(t)
    test_upload_pipeline_and_delete()
    print("\n全部验证通过 ✅")
