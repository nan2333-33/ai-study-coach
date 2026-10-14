from . import Base
from sqlalchemy import Column, String, Date, Integer, Boolean, Numeric, DateTime, func
from sqlalchemy.types import JSON


class LearningSession(Base):
    """表11：学习会话记录表（Session 级 checklist）"""

    __tablename__ = "learning_sessions"
    id = Column(String(36), primary_key=True)
    session_date = Column(Date, nullable=False)
    duration_minutes = Column(Integer, default=0)
    viewed_material = Column(Boolean, default=False)
    chatted = Column(Boolean, default=False)
    quizzed = Column(Boolean, default=False)
    material_ids = Column(JSON)
    chat_session_id = Column(String(36))
    quiz_id = Column(String(36))
    quiz_score = Column(Numeric(3, 1))
    created_at = Column(DateTime, server_default=func.now())
