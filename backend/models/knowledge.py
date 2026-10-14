from . import Base
from sqlalchemy import Column, String, Text, DateTime, Numeric, Integer, func, text


class KnowledgePoint(Base):
    """表9：知识点表"""

    __tablename__ = "knowledge_points"
    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    material_id = Column(String(36))
    chapter = Column(String(100))
    description = Column(Text)
    # 语义聚类后的代表知识点 id。NULL 表示还没跑过聚类。
    # 大模型每次出题给知识点起的名字略有出入（「Transformer的起源」/「Transformer 定义与起源」），
    # 会以不同 id 落库；聚类后这些行都指向同一个 canonical_id，统计时按它分组。
    canonical_id = Column(String(36))
    created_at = Column(DateTime, server_default=func.now())


def ensure_canonical_id_column(engine):
    """给老库补 `canonical_id` 列（create_all 不会给已存在的表加列）。"""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(knowledge_points)"))]
        if "canonical_id" not in cols:
            conn.execute(text("ALTER TABLE knowledge_points ADD COLUMN canonical_id VARCHAR(36)"))


class ErrorBook(Base):
    """表10：错题本表"""

    __tablename__ = "error_book"
    id = Column(String(36), primary_key=True)
    question_id = Column(String(36), nullable=False)
    submission_id = Column(String(36), nullable=False)
    user_answer = Column(Text, nullable=False)
    reference_answer = Column(Text)
    score = Column(Numeric(2, 1), nullable=False)
    knowledge_point_id = Column(String(36))
    source_material_id = Column(String(36))
    source_page_number = Column(Integer)
    review_count = Column(Integer, default=0)
    next_review_at = Column(DateTime)
    ease_factor = Column(Numeric(2, 1), default=2.5)  # SM-2 难度因子
    interval_days = Column(Integer, default=0)  # SM-2 间隔天数
    status = Column(String(20), default="active")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
