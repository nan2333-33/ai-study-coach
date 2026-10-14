from . import Base
from sqlalchemy import Column, String, Text, DateTime, Integer, func
from sqlalchemy.types import JSON

from datetime import datetime, timezone


def _utcnow():
    """naive UTC 时间，带微秒。

    不能用 SQLite 的 CURRENT_TIMESTAMP（server_default=func.now()）：它只精确到秒，
    同一轮对话的「提问」和「回答」会拿到完全相同的时间戳，导致
    ORDER BY created_at 的顺序变成未定义（可能回答排在提问前面），
    侧栏的"最后一条消息"也会随机取到其中一个。
    naive（不带时区）是为了和存量数据的 UTC 字符串保持一致，避免时区混用导致排序错乱。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ChatSession(Base):
    """表3：对话会话表"""

    __tablename__ = "chat_sessions"
    id = Column(String(36), primary_key=True)
    title = Column(String(200))
    material_ids = Column(JSON)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow, server_default=func.now())
    updated_at = Column(DateTime, default=_utcnow, server_default=func.now(), onupdate=_utcnow)


class ChatMessage(Base):
    """表4：对话消息表"""

    __tablename__ = "chat_messages"
    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON)
    token_count = Column(Integer)
    created_at = Column(DateTime, default=_utcnow, server_default=func.now())
