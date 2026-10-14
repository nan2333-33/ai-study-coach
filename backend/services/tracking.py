"""学习行为统计：只统计「真做真记」的硬数据。

为什么不再有学习时长
--------------------
早期版本会在周报和进度页显示「学习时长」，但那个数字是**推算**出来的
（按聊天/答题/上传的时间戳间隔折算），不是用户真实花的时间。
一个学习产品放一个自己推算的数字，用户一旦发现对不上（明明只学了 20 分钟却写 190 分钟），
会连带着怀疑其他数据。所以主指标换成 **`question_count`（答题数）**——
每答一题就落一条 `quiz_answers`，是实打实计数出来的。

同理，这里也不保留任何"估算"口径：
- 连续学习天数：按**有学习行为的日期**数，不折算时长
- 每日明细：当天答了几题 / 有没有聊天 / 有没有传资料，都是可验证的事实

数据来源
--------
    quiz_answers + quiz_submissions   答题数（按 submitted_at 归属到当天）
    chat_messages                     聊天问答
    materials                         上传资料
"""

from datetime import date, datetime, timedelta

from models.chat import ChatMessage
from models.quiz import QuizAnswer, QuizSubmission
from models.material import Material


def _cache(s, key, builder):
    """同一请求内复用查询结果（Session.info 是 SQLAlchemy 给用户挂数据的字典）。"""
    if key not in s.info:
        s.info[key] = builder()
    return s.info[key]


def _to_date(ts):
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, date):
        return ts
    return None


def question_dates(s):
    """每次提交对应的 (日期, 答题数)。用于统计任意区间内的答题量。"""
    def build():
        rows = (
            s.query(QuizSubmission.id, QuizSubmission.submitted_at)
            .all()
        )
        counts = (
            s.query(QuizAnswer.submission_id, )
            .all()
        )
        per = {}
        for (sid,) in counts:
            per[sid] = per.get(sid, 0) + 1
        out = []
        for sid, submitted_at in rows:
            d = _to_date(submitted_at)
            if d is None:
                continue
            out.append((d, per.get(sid, 0)))
        return out

    return _cache(s, "_question_dates", build)


def question_count(s, start=None, end=None):
    """区间内的答题数；不传区间就是累计答题数。"""
    total = 0
    for d, cnt in question_dates(s):
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        total += cnt
    return total


def activity_days(s):
    """{日期: 行为集合}，行为取值 chat / quiz / material。"""
    def build():
        days = {}

        def mark(ts, kind):
            d = _to_date(ts)
            if d is None:
                return
            days.setdefault(d, set()).add(kind)

        for (ts,) in s.query(ChatMessage.created_at).all():
            mark(ts, "chat")
        for (ts,) in s.query(QuizSubmission.submitted_at).all():
            mark(ts, "quiz")
        for (ts,) in s.query(Material.created_at).all():
            mark(ts, "material")
        return days

    return _cache(s, "_activity_days", build)


def streak_days(s):
    """连续学习天数：从今天（或昨天）往前数有学习行为的连续天数。

    今天还没学时不算断签——晚上才打开 App 的用户不该被判成断了。
    """
    days = set(activity_days(s).keys())
    if not days:
        return 0
    cur = date.today()
    if cur not in days:
        cur -= timedelta(days=1)
    streak = 0
    while cur in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def daily_detail(s, limit=30):
    """按天倒序返回学习行为明细（供 /api/progress/sessions 用）。"""
    days = activity_days(s)
    per_day = {}
    for d, cnt in question_dates(s):
        per_day[d] = per_day.get(d, 0) + cnt

    out = []
    for d in sorted(days, reverse=True)[:limit]:
        kinds = days[d]
        out.append(
            {
                "date": d.isoformat(),
                "questionCount": per_day.get(d, 0),
                "chatted": "chat" in kinds,
                "quizzed": "quiz" in kinds,
                "uploadedMaterial": "material" in kinds,
            }
        )
    return out
