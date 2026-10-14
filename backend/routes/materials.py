import os

from flask import Blueprint, request, current_app

from utils.response import ok, fail
from utils.idgen import gen_id
from config import Config
from models.material import Material, MaterialChunk, MaterialNote
from services.vector_store import vector_store
from services.pipeline import process_material_async

bp = Blueprint("materials", __name__, url_prefix="/api/materials")

ALLOWED = {"pdf", "ppt", "pptx", "doc", "docx", "md", "markdown", "txt"}
# 入库与返回时统一成前端认识的简短类型（图标样式靠它匹配）
TYPE_ALIAS = {"pptx": "ppt", "docx": "doc", "markdown": "md"}


def _norm_type(ext):
    return TYPE_ALIAS.get(ext, ext)


def _session():
    return current_app.SessionLocal


@bp.post("/upload")
def upload():
    # PRD M-01 文件上传：支持 PDF/PPT/Word/Markdown/TXT
    file = request.files.get("file")
    if not file or not file.filename:
        return fail("缺少上传文件", code=400)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED:
        return fail(f"不支持的文件类型: .{ext}", code=400)

    data = file.read()
    if len(data) > Config.UPLOAD_MAX_MB * 1024 * 1024:
        return fail(f"文件超过 {Config.UPLOAD_MAX_MB}MB 上限", code=400)

    title = request.form.get("title") or file.filename
    category = request.form.get("category") or None

    material_id = gen_id("mat")
    safe_name = f"{material_id}_{file.filename}"
    save_path = os.path.join(Config.UPLOAD_DIR, safe_name)
    with open(save_path, "wb") as f:
        f.write(data)

    with _session()() as s:
        m = Material(
            id=material_id,
            title=title,
            file_name=file.filename,
            file_type=_norm_type(ext),
            file_path=save_path,
            file_size=len(data),
            category=category,
            status="processing",
            chunk_count=0,
        )
        s.add(m)
        s.commit()
        created = m.created_at.isoformat() if m.created_at else None

    # 后台异步处理：读文字 → 切块 → 向量化 → 存好，不阻塞响应
    process_material_async(material_id)

    return ok(
        data={
            "materialId": material_id,
            "title": title,
            "fileName": file.filename,
            "fileType": _norm_type(ext),
            "status": "processing",
            "chunkCount": 0,
            "createdAt": created,
        }
    )


@bp.get("")
def list_materials():
    # PRD 资料列表：按 category/status 筛选 + 分页
    category = request.args.get("category")
    status = request.args.get("status")
    page = max(1, int(request.args.get("page", 1)))
    page_size = max(1, int(request.args.get("pageSize", 20)))

    with _session()() as s:
        q = s.query(Material)
        if category:
            q = q.filter(Material.category == category)
        if status:
            q = q.filter(Material.status == status)
        total = q.count()
        rows = (
            q.order_by(Material.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        list_data = []
        for m in rows:
            item = {
                "materialId": m.id,
                "title": m.title,
                "fileType": _norm_type(m.file_type or ""),
                "status": m.status,
                "chunkCount": m.chunk_count,
                "category": m.category,
                "createdAt": m.created_at.isoformat() if m.created_at else None,
            }
            # 解析失败时把原因带回前端，卡片上直接可见，便于定位（密钥没配、文件损坏等）
            if m.status == "error" and m.error_message:
                item["errorMessage"] = m.error_message
            list_data.append(item)
    return ok(data={"total": total, "list": list_data})


@bp.get("/<material_id>")
def get_material(material_id):
    # PRD 资料详情：含分块列表（用于查看处理进度 / 来源）
    with _session()() as s:
        m = s.get(Material, material_id)
        if not m:
            return fail("资料不存在", code=404)
        chunks = (
            s.query(MaterialChunk)
            .filter(MaterialChunk.material_id == material_id)
            .order_by(MaterialChunk.chunk_index)
            .all()
        )
        chunk_data = [
            {
                "chunkId": c.id,
                "chunkIndex": c.chunk_index,
                "pageNumber": c.page_number,
                "preview": (c.content[:120] + "…") if len(c.content) > 120 else c.content,
            }
            for c in chunks
        ]
        data = {
            "materialId": m.id,
            "title": m.title,
            "fileType": _norm_type(m.file_type or ""),
            "status": m.status,
            "chunkCount": m.chunk_count,
            "category": m.category,
            "chunks": chunk_data,
            "createdAt": m.created_at.isoformat() if m.created_at else None,
        }
        # 解析失败时把原因带回前端，方便定位（密钥没配、文件损坏等）
        if m.status == "error" and m.error_message:
            data["errorMessage"] = m.error_message
    return ok(data=data)


@bp.delete("/<material_id>")
def delete_material(material_id):
    # PRD 删除资料：文件 + 向量（Chroma）+ 数据库记录 一起删干净
    with _session()() as s:
        m = s.get(Material, material_id)
        if not m:
            return fail("资料不存在", code=404)

        # 1) 删除磁盘文件
        if m.file_path and os.path.exists(m.file_path):
            try:
                os.remove(m.file_path)
            except OSError:
                pass

        # 2) 删除向量（Chroma）
        vector_store.delete_material(material_id)

        # 3) 删除数据库记录：分块 + 笔记 + 资料本身
        s.query(MaterialChunk).filter(
            MaterialChunk.material_id == material_id
        ).delete()
        s.query(MaterialNote).filter(
            MaterialNote.material_id == material_id
        ).delete()
        s.delete(m)
        s.commit()
    return ok(data={"materialId": material_id, "deleted": True})


@bp.post("/<material_id>/retry")
def retry_material(material_id):
    """重新解析：清掉旧分块与旧向量，重新走「读文字→切块→向量化→存好」（后台异步）。"""
    with _session()() as s:
        m = s.get(Material, material_id)
        if not m:
            return fail("资料不存在", code=404)
        # 清掉旧结果，避免重复累积
        s.query(MaterialChunk).filter(
            MaterialChunk.material_id == material_id
        ).delete()
        m.status = "processing"
        m.chunk_count = 0
        m.error_message = None
        s.commit()

    vector_store.delete_material(material_id)
    process_material_async(material_id)
    return ok(data={"materialId": material_id, "status": "processing"})


@bp.get("/<material_id>/notes")
def get_note(material_id):
    # PRD C-07 资料笔记
    with _session()() as s:
        note = (
            s.query(MaterialNote)
            .filter(MaterialNote.material_id == material_id)
            .first()
        )
        if not note:
            return ok(
                data={"materialId": material_id, "content": "", "contentLength": 0}
            )
        return ok(
            data={
                "noteId": note.id,
                "materialId": note.material_id,
                "content": note.content,
                "contentLength": note.content_length,
            }
        )


@bp.put("/<material_id>/notes")
def save_note(material_id):
    # PRD C-07 保存/覆盖笔记（前端停笔自动保存）
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    with _session()() as s:
        note = (
            s.query(MaterialNote)
            .filter(MaterialNote.material_id == material_id)
            .first()
        )
        if note:
            note.content = content
            note.content_length = len(content)
        else:
            note = MaterialNote(
                id=gen_id("nt"),
                material_id=material_id,
                content=content,
                content_length=len(content),
            )
            s.add(note)
        s.commit()
        return ok(
            data={
                "noteId": note.id,
                "materialId": material_id,
                "content": content,
                "contentLength": len(content),
            }
        )
