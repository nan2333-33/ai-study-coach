import json

from flask import Blueprint, request, current_app, Response, stream_with_context

from utils.response import ok, fail
from utils.idgen import gen_id
from models.chat import ChatSession, ChatMessage
from models.material import Material
from services.clients import llm_client, embedding_client
from services.vector_store import vector_store
from services.prompts import PROMPT_CHAT_TUTOR

bp = Blueprint("chat", __name__, url_prefix="/api/chat")

_HISTORY_TURNS = 12  # 多轮对话带上的历史消息条数（C-03）


def _session():
    return current_app.SessionLocal


def _retrieve(question, material_ids):
    """C-01 RAG 检索：问题向量化 → Chroma 余弦检索 → 过滤低相关片段。"""
    query_vec = embedding_client.embed([question])[0]
    return vector_store.search(query_vec, material_ids=material_ids)


def _build_context(hits):
    """把检索到的片段拼成上下文，带资料标题与页码（供 C-02 来源引用）。"""
    parts = []
    for h in hits:
        title = h.get("materialTitle") or h.get("materialId")
        page = h.get("pageNumber")
        page_txt = f"第{page}页" if page else "未知页码"
        parts.append(f"[《{title}》{page_txt}]\n{h['content']}")
    return "\n\n".join(parts)


def _build_sources(s, hits):
    """C-02 来源引用：检索命中 → 前端可展示的来源列表。"""
    sources = []
    for h in hits:
        title = h.get("materialTitle")
        if not title:
            mat = s.get(Material, h.get("materialId"))
            title = mat.title if mat else h.get("materialId")
        snippet = h["content"]
        sources.append(
            {
                "materialId": h.get("materialId"),
                "title": title,
                "pageNumber": h.get("pageNumber"),
                "chunkIndex": h.get("chunkIndex"),
                "snippet": snippet[:200] + ("…" if len(snippet) > 200 else ""),
            }
        )
    return sources


def _build_messages(s, session_id, question, context):
    """系统提示 + 多轮历史（C-03）+ 带资料上下文的当前提问。"""
    history = (
        s.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(_HISTORY_TURNS)
        .all()
    )
    history = list(reversed(history))

    messages = [{"role": "system", "content": PROMPT_CHAT_TUTOR}]
    for m in history:
        messages.append({"role": m.role, "content": m.content})
    messages.append(
        {
            "role": "user",
            "content": (
                f"以下是与问题相关的资料片段：\n\n{context}\n\n"
                f"请基于上述资料回答以下问题：\n{question}"
            ),
        }
    )
    return messages


def _persist(session_id, question, answer, sources):
    """落库：用户消息 + 助手消息，返回助手消息。"""
    with _session()() as s:
        user_msg = ChatMessage(
            id=gen_id("msg"), session_id=session_id, role="user", content=question
        )
        ai_msg = ChatMessage(
            id=gen_id("msg"),
            session_id=session_id,
            role="assistant",
            content=answer,
            sources=sources,
        )
        s.add(user_msg)
        s.add(ai_msg)
        session = s.get(ChatSession, session_id)
        if session:
            session.message_count = (session.message_count or 0) + 2
        s.commit()
        return (
            ai_msg.id,
            ai_msg.created_at.isoformat() if ai_msg.created_at else None,
        )


def _prepare(session_id, question, material_ids):
    """流式与非流式共用的前置阶段：校验会话 → 检索 → 组装 messages。

    返回 (messages, sources)；会话不存在或检索失败时抛 ValueError。
    """
    with _session()() as s:
        session = s.get(ChatSession, session_id)
        if not session:
            raise ValueError("会话不存在")
        material_ids = material_ids or session.material_ids
        try:
            hits = _retrieve(question, material_ids)
        except Exception as e:
            # 向量模型未配置等原因导致检索失败，明确告知，不静默降级
            raise ValueError(f"资料检索失败：{e}")

        context = _build_context(hits) or "（本次未检索到相关资料片段）"
        sources = _build_sources(s, hits)
        messages = _build_messages(s, session_id, question, context)
    return messages, sources


@bp.post("/sessions")
def create_session():
    # PRD 创建会话，绑定 materialIds
    body = request.get_json(silent=True) or {}
    material_ids = body.get("materialIds")
    session_id = gen_id("ses")
    with _session()() as s:
        row = ChatSession(
            id=session_id,
            title=body.get("title") or "新对话",
            material_ids=material_ids,
            message_count=0,
        )
        s.add(row)
        s.commit()
        return ok(
            data={
                "sessionId": row.id,
                "title": row.title,
                "materialIds": row.material_ids,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
            }
        )


@bp.post("/sessions/<session_id>/messages")
def send_message(session_id):
    """C-01 RAG 检索 → C-02 来源引用 → C-03 多轮 → C-04 多资料交叉。（非流式，保留做兜底）"""
    body = request.get_json(silent=True) or {}
    question = (body.get("message") or "").strip()
    if not question:
        return fail("message 不能为空", code=400)

    try:
        messages, sources = _prepare(session_id, question, body.get("materialIds"))
    except ValueError as e:
        code = 404 if str(e) == "会话不存在" else 500
        return fail(str(e), code=code)

    try:
        answer = llm_client.complete(messages, temperature=0.6)
    except Exception as e:
        return fail(f"大模型调用失败：{e}", code=500)

    message_id, created = _persist(session_id, question, answer, sources)

    return ok(
        data={
            "messageId": message_id,
            "role": "assistant",
            "content": answer,
            "sources": sources,
            "createdAt": created,
        }
    )


def _sse(event, data):
    """拼一帧 SSE：event 行 + data 行 + 空行结束。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@bp.post("/sessions/<session_id>/messages/stream")
def send_message_stream(session_id):
    """流式版本：SSE 逐段推送，前端做打字机效果。

    事件序列：
        meta  → { sources }          检索完立刻下发，引用面板可以先出现
        delta → { text }             每个字/词一段，可能很多帧
        done  → { messageId, content, sources, createdAt }  落库完成
        error → { msg }              出错（此时前端显示错误气泡）
    """
    body = request.get_json(silent=True) or {}
    question = (body.get("message") or "").strip()
    if not question:
        return fail("message 不能为空", code=400)

    # 前置阶段（检索/组装）在流开始之前完成：这里出错直接返回 JSON，
    # 前端通过 content-type 判断，不会把它当成 SSE 去解析。
    try:
        messages, sources = _prepare(session_id, question, body.get("materialIds"))
    except ValueError as e:
        code = 404 if str(e) == "会话不存在" else 500
        return fail(str(e), code=code)

    def generate():
        yield _sse("meta", {"sources": sources})

        buf = []
        try:
            for delta in llm_client.complete_stream(messages, temperature=0.6):
                buf.append(delta)
                yield _sse("delta", {"text": delta})
        except Exception as e:
            # 一个字都没吐出来才报错；已经吐了部分则当作正常结束，保住已显示内容
            if not buf:
                yield _sse("error", {"msg": f"大模型调用失败：{e}"})
                return

        answer = "".join(buf).strip()
        if not answer:
            # 极端兜底：某些兼容接口 stream 不下发 content，回退到非流式
            try:
                answer = llm_client.complete(messages, temperature=0.6)
            except Exception as e:
                yield _sse("error", {"msg": f"大模型调用失败：{e}"})
                return
            yield _sse("delta", {"text": answer})

        try:
            message_id, created = _persist(session_id, question, answer, sources)
        except Exception as e:
            yield _sse("error", {"msg": f"回复保存失败：{e}"})
            return

        yield _sse(
            "done",
            {
                "messageId": message_id,
                "role": "assistant",
                "content": answer,
                "sources": sources,
                "createdAt": created,
            },
        )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # 关掉 nginx 一类反向代理的缓冲
            "Connection": "keep-alive",
        },
    )


@bp.get("/sessions/<session_id>/messages")
def list_messages(session_id):
    # PRD 会话历史（分页）
    page = max(1, int(request.args.get("page", 1)))
    page_size = max(1, int(request.args.get("pageSize", 20)))
    with _session()() as s:
        q = s.query(ChatMessage).filter(ChatMessage.session_id == session_id)
        total = q.count()
        rows = (
            q.order_by(ChatMessage.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        list_data = [
            {
                "messageId": m.id,
                "role": m.role,
                "content": m.content,
                "sources": m.sources,
                "createdAt": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]
    return ok(data={"total": total, "list": list_data})


@bp.get("/sessions")
def list_sessions():
    # PRD 会话列表
    with _session()() as s:
        rows = s.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
        list_data = []
        for r in rows:
            # 侧栏预览取「最后一条提问」而不是最后一条回答：
            # 扫历史时认自己的问题比认 AI 的回答快得多
            last = (
                s.query(ChatMessage)
                .filter(ChatMessage.session_id == r.id, ChatMessage.role == "user")
                .order_by(ChatMessage.created_at.desc())
                .first()
            )
            list_data.append(
                {
                    "sessionId": r.id,
                    "title": r.title,
                    "lastMessage": last.content if last else None,
                    "materialCount": len(r.material_ids or []),
                    "createdAt": r.created_at.isoformat() if r.created_at else None,
                    "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
                }
            )
    return ok(data={"total": len(list_data), "list": list_data})


@bp.delete("/sessions/<session_id>")
def delete_session(session_id):
    with _session()() as s:
        s.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        row = s.get(ChatSession, session_id)
        if row:
            s.delete(row)
        s.commit()
    return ok(data={"sessionId": session_id, "deleted": True})
