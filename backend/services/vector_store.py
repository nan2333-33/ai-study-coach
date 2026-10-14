"""向量存储：ChromaDB 持久化，文本向量由 EmbeddingClient 生成。

对应 PRD M-04（向量化与存储）：
- 单一 collection `material_chunks`，每条 chunk 存：
    id        : "{material_id}_{chunk_index}"
    embedding : 由向量模型生成
    document  : 原文
    metadata  : {material_id, chunk_index, page_number, material_title, material_file_type}
- 检索：余弦距离（hnsw:space=cosine），相似度低于阈值的相关片段直接丢弃
"""
import os

from config import Config

# 关闭 Chroma 匿名遥测
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "true")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

os.makedirs(Config.CHROMA_DIR, exist_ok=True)

import chromadb

_COLLECTION = "material_chunks"

_client = chromadb.PersistentClient(path=Config.CHROMA_DIR)


def _ensure_collection():
    """拿到 collection，并保证它的向量维度与 Config.EMBED_DIM 一致。

    ChromaDB 的 get_or_create_collection 在 collection 已存在时会沿用旧维度，
    一旦换过向量模型（或改过 EMBED_DIM），写入就会报
    "Collection expecting embedding with dimension of X, got Y"。
    这里主动做一次维度自检，不一致才重建，避免用户手动删目录。

    注意：**只有确认维度真的不匹配时才重建**。
    早先版本会在「空库」时也删掉重建，配合 Flask 的 debug 重载会不断生成新的
    collection UUID，导致正在运行的解析线程持有失效的引用，报
    "Collection [...] does not exist"。空库没有维度问题，不要动它。
    """
    dim = int(Config.EMBED_DIM)

    try:
        col = _client.get_collection(name=_COLLECTION)
    except Exception:
        col = None

    if col is None:
        return _client.create_collection(
            name=_COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    # 已有 collection：只有确实存过向量、且维度与配置不符时才重建
    existing = None
    try:
        peek = col.peek(limit=1)
        embs = peek.get("embeddings")
        if embs is not None and len(embs) > 0 and embs[0] is not None:
            existing = len(embs[0])
    except Exception:
        existing = None

    if existing is not None and existing != dim:
        print(
            f"[vector_store] 向量库维度 {existing} 与配置 EMBED_DIM={dim} 不一致，"
            f"自动重建 collection（旧向量作废，资料需重新解析）",
            flush=True,
        )
        _client.delete_collection(name=_COLLECTION)
        col = _client.create_collection(
            name=_COLLECTION, metadata={"hnsw:space": "cosine"}
        )
    return col


_collection = None


def _get_collection():
    global _collection
    if _collection is None:
        _collection = _ensure_collection()
    return _collection


def _call(action):
    """执行一次向量库操作。

    若 collection 在别处被重建（UUID 失效，报 "does not exist"），
    重新获取一次再重试，避免整个解析任务直接失败。
    """
    try:
        return action(_get_collection())
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if "does not exist" in msg or "NotFound" in msg or "not found" in msg.lower():
            global _collection
            _collection = _ensure_collection()
            return action(_collection)
        raise


class VectorStore:
    def add_chunks(self, material_id, title, file_type, chunks, embeddings):
        """embeddings: List[List[float]]，与 chunks 一一对应。"""
        if not chunks:
            return
        ids = [f"{material_id}_{c.chunk_index}" for c in chunks]
        docs = [c.content for c in chunks]
        metas = [
            {
                "material_id": material_id,
                "chunk_index": c.chunk_index,
                "page_number": c.page_number,
                "material_title": title,
                "material_file_type": file_type,
            }
            for c in chunks
        ]
        _call(
            lambda col: col.upsert(
                ids=ids, embeddings=embeddings, documents=docs, metadatas=metas
            )
        )

    def delete_material(self, material_id):
        """删除某资料的全部向量。"""
        _call(lambda col: col.delete(where={"material_id": material_id}))

    def search(self, query_vector, material_ids=None, top_k=None, min_score=None):
        """余弦相似度检索；min_score 以下的直接丢弃（对应「相关性太低不要」）。"""
        top_k = top_k or Config.RETRIEVE_TOP_K
        min_score = min_score if min_score is not None else Config.RETRIEVE_MIN_SCORE
        where = {"material_id": {"$in": material_ids}} if material_ids else None
        res = _call(
            lambda col: col.query(
                query_embeddings=[query_vector],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        results = []
        for i, meta in enumerate(metas):
            sim = 1 - float(dists[i])
            if sim < min_score:
                continue
            results.append(
                {
                    "chunkIndex": meta.get("chunk_index"),
                    "pageNumber": meta.get("page_number"),
                    "materialId": meta.get("material_id"),
                    "materialTitle": meta.get("material_title"),
                    "content": docs[i],
                    "score": round(sim, 4),
                }
            )
        return results


vector_store = VectorStore()
