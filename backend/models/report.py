from . import Base
from sqlalchemy import Column, String, Date, Integer, Numeric, Text, DateTime, func, text
from sqlalchemy.types import JSON


class WeeklyReport(Base):
    """表12：周报表

    注意：这里不再存「学习时长」。时长是推算值，不可验证；
    改用 `question_count`（本周答题数）——真做真记的硬数据。
    """

    __tablename__ = "weekly_reports"
    id = Column(String(36), primary_key=True)
    week_start = Column(Date, nullable=False)
    week_end = Column(Date, nullable=False)
    question_count = Column(Integer, default=0)
    question_count_last = Column(Integer, default=0)
    new_materials = Column(Integer, nullable=False)
    covered_chunks = Column(Integer, nullable=False)
    coverage_rate = Column(Numeric(4, 3), nullable=False)
    accuracy_this_week = Column(Numeric(4, 3))
    accuracy_last_week = Column(Numeric(4, 3))
    accuracy_change = Column(Numeric(4, 3))
    weak_points = Column(JSON, nullable=False)
    next_week_plan = Column(JSON, nullable=False)
    motivation = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


def ensure_question_count_column(engine):
    """给老库补 `question_count` 列（create_all 不会给已存在的表加列）。

    旧的 `study_minutes` 列不再读写，留在表里不影响（SQLite 老版本不支持 DROP COLUMN）。

    存量周报不会补成 0——那样本周明明答了 78 题，周报却写 0 题，用户一眼就看出对不上。
    答题数是硬计数，按周报自己的周期重算一遍即可，结果和当时生成时完全一致。
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(weekly_reports)"))]
        for col in ("question_count", "question_count_last"):
            if col not in cols:
                conn.execute(text(f"ALTER TABLE weekly_reports ADD COLUMN {col} INTEGER"))

    _backfill_question_counts(engine)


def _backfill_question_counts(engine):
    """按「周报自己的周期」重算答题数，填进存量记录。

    只补 NULL 或 0 的行：0 在老库里代表"没统计过"，不代表"那周没答题"
    （真没答题的行重算出来也是 0，补了不亏）。
    """
    from datetime import timedelta

    from sqlalchemy.orm import Session

    from models.quiz import QuizAnswer, QuizSubmission

    try:
        with Session(engine) as s:
            per_submission = {}
            for (sid,) in s.query(QuizAnswer.submission_id).all():
                per_submission[sid] = per_submission.get(sid, 0) + 1
            submissions = s.query(QuizSubmission.id, QuizSubmission.submitted_at).all()

            def count_between(start, end):
                total = 0
                for sid, submitted_at in submissions:
                    if submitted_at is None:
                        continue
                    d = submitted_at.date()
                    if start <= d <= end:
                        total += per_submission.get(sid, 0)
                return total

            changed = 0
            for row in s.query(WeeklyReport).all():
                if row.question_count:
                    continue
                start, end = row.week_start, row.week_end
                span = (end - start).days + 1
                row.question_count = count_between(start, end)
                row.question_count_last = count_between(
                    start - timedelta(days=span), start - timedelta(days=1)
                )
                changed += 1
            if changed:
                s.commit()
    except Exception:
        # 回填失败不影响启动：新周报生成时会写入正确值
        pass
