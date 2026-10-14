"""数据库模型：13 张表，完全按 PRD 数据库设计实现。

导入方式：
    from models import Material, ChatSession, Quiz, ...
    from models import Base
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# 触发子模块加载，确保表注册到 Base.metadata
from .material import Material, MaterialChunk, MaterialNote
from .chat import ChatSession, ChatMessage
from .quiz import Quiz, QuizQuestion, QuizSubmission, QuizAnswer
from .knowledge import KnowledgePoint, ErrorBook
from .learning import LearningSession
from .report import WeeklyReport

__all__ = [
    "Base",
    "Material",
    "MaterialChunk",
    "MaterialNote",
    "ChatSession",
    "ChatMessage",
    "Quiz",
    "QuizQuestion",
    "QuizSubmission",
    "QuizAnswer",
    "KnowledgePoint",
    "ErrorBook",
    "LearningSession",
    "WeeklyReport",
]
