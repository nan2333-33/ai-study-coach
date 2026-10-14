from . import Base
from sqlalchemy import Column, String, Text, DateTime, Numeric, Integer, func
from sqlalchemy.types import JSON


class Quiz(Base):
    """表5：测验表"""

    __tablename__ = "quizzes"
    id = Column(String(36), primary_key=True)
    material_ids = Column(JSON, nullable=False)
    question_count = Column(Integer, nullable=False)
    type_ratio = Column(JSON)
    difficulty = Column(String(20), default="basic")
    status = Column(String(20), nullable=False, default="ready")
    created_at = Column(DateTime, server_default=func.now())


class QuizQuestion(Base):
    """表6：题目表"""

    __tablename__ = "quiz_questions"
    id = Column(String(36), primary_key=True)
    quiz_id = Column(String(36), nullable=False, index=True)
    type = Column(String(20), nullable=False)
    question = Column(Text, nullable=False)
    options = Column(JSON)
    correct_answer = Column(String(50), nullable=False)
    reference_answer = Column(Text)
    source_material_id = Column(String(36))
    source_page_number = Column(Integer)
    source_chunk_index = Column(Integer)
    knowledge_point_id = Column(String(36))
    # 出题顺序。不能只靠 created_at 排序：SQLite 的 CURRENT_TIMESTAMP 只到秒，
    # 一套题的所有题目是同一次提交写入的，时间戳完全相同，
    # 于是排序会退化成按随机字符串 id 排，批改结果就和题目对不上了
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


def ensure_order_index_column(engine):
    """给 quiz_questions 补 order_index 列，并把老数据按当时的出题顺序回填。

    SQLAlchemy 的 create_all 只建表、不会给已存在的表加列，所以必须手动补。
    回填用 SQLite 的 rowid（等于插入顺序）还原出题顺序；非 SQLite 直接跳过。
    """
    if engine.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(quiz_questions)"))]
        if "order_index" not in cols:
            conn.execute(text("ALTER TABLE quiz_questions ADD COLUMN order_index INTEGER"))
        conn.execute(
            text(
                """
                UPDATE quiz_questions SET order_index = (
                    SELECT COUNT(*) FROM quiz_questions q2
                    WHERE q2.quiz_id = quiz_questions.quiz_id
                      AND q2.rowid <= quiz_questions.rowid
                )
                WHERE order_index IS NULL
                """
            )
        )


class QuizSubmission(Base):
    """表7：提交记录表"""

    __tablename__ = "quiz_submissions"
    id = Column(String(36), primary_key=True)
    quiz_id = Column(String(36), nullable=False)
    total_score = Column(Numeric(3, 1), nullable=False)
    max_score = Column(Numeric(3, 1), nullable=False)
    accuracy = Column(Numeric(4, 3), nullable=False)
    duration_minutes = Column(Integer)
    submitted_at = Column(DateTime, server_default=func.now())


class QuizAnswer(Base):
    """表8：答题明细表"""

    __tablename__ = "quiz_answers"
    id = Column(String(36), primary_key=True)
    submission_id = Column(String(36), nullable=False, index=True)
    question_id = Column(String(36), nullable=False)
    user_answer = Column(Text, nullable=False)
    is_correct = Column(Integer)  # 0/1，简答题留空
    score = Column(Numeric(2, 1), nullable=False)
    explanation = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
