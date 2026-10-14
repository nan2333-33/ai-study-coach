from flask import Blueprint

from utils.response import ok

# PRD 2.3：GET /api/review/scheduled（独立前缀，不属于 /api/quiz）
bp = Blueprint("review", __name__, url_prefix="/api/review")


@bp.get("/scheduled")
def review_scheduled():
    # TODO: 间隔重复调度（Q-08，P1）—— 今日待复习错题
    return ok(data={"dueCount": 0, "items": []})
