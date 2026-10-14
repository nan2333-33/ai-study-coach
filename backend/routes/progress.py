import re
from datetime import date, timedelta

from flask import Blueprint, request, current_app
from sqlalchemy import func

from utils.response import ok, fail
from models.material import Material, MaterialChunk, MaterialNote
from models.quiz import QuizQuestion, QuizAnswer, QuizSubmission
from models.knowledge import KnowledgePoint, ErrorBook
from models.learning import LearningSession  # noqa: F401  (PRD 表11，当前指标已改用答题数，暂不读写)
from models.chat import ChatMessage
# 复用资料模块的扩展名归一（兼容改动前入库的 pptx/docx 等）
from routes.materials import _norm_type
from services import tracking
from services.kp_cluster import DEFAULT_THRESHOLD, merge_knowledge_points, reset_canonical

bp = Blueprint("progress", __name__, url_prefix="/api/progress")


def _session():
    return current_app.SessionLocal


def _level(mastery):
    """掌握度分级：熟练 / 掌握 / 薄弱。"""
    if mastery >= 0.8:
        return "熟练"
    if mastery >= 0.5:
        return "掌握"
    return "薄弱"


def _norm_kp_name(name):
    """知识点名归一化：忽略大小写与空白差异，用于合并同名知识点。"""
    return re.sub(r"\s+", "", (name or "")).lower()


def canonical_name(s, kp):
    """知识点规范名：跑过语义聚类后用聚类代表的名字，否则用自己名字。

    聚类把「Transformer的起源 / Transformer 定义与起源」这类同义写法并成一组，
    组内所有行的 canonical_id 指向同一个代表 id；展示统一用代表名，
    否则前端会看到两条同名不同 id 的知识点。
    """
    cid = getattr(kp, "canonical_id", None)
    if not cid or cid == kp.id:
        return kp.name, kp.id
    canon = s.get(KnowledgePoint, cid)
    if canon and canon.name:
        return canon.name, cid
    return kp.name, cid or kp.id


def _kp_group_key(kp, cid):
    """分组键：优先按聚类代表 id，没跑过聚类时退回名称归一化。"""
    return ("c:" + cid) if cid else ("n:" + _norm_kp_name(kp.name))


_merge_last_try = 0.0
_MERGE_MIN_INTERVAL = 60  # 秒：聚类要调 embedding，别让每次刷新都重跑


def _maybe_merge(s):
    """有新知识点（canonical_id 为空）时顺手跑一次语义聚类。

    失败不影响页面——退回按名称归一化分组。
    """
    global _merge_last_try
    import time

    pending = (
        s.query(func.count(KnowledgePoint.id))
        .filter(
            (KnowledgePoint.canonical_id.is_(None)) | (KnowledgePoint.canonical_id == "")
        )
        .scalar()
        or 0
    )
    if not pending:
        return

    now = time.time()
    if now - _merge_last_try < _MERGE_MIN_INTERVAL:
        return
    _merge_last_try = now

    try:
        from services.kp_cluster import merge_knowledge_points

        res = merge_knowledge_points(s)
        s.commit()
        current_app.logger.info(
            "知识点语义聚类：%d 行 → %d 组（合并掉 %d 行）",
            res["total"], res["groups"], res["merged"],
        )
    except Exception as exc:  # 聚类失败绝不能让进度页 500
        s.rollback()
        current_app.logger.warning("知识点语义聚类失败，退回名称归一化：%s", exc)


def _knowledge_mastery(s):
    """知识点掌握度：按知识点统计答题平均得分与题量（P-02/P-06 的数据基础）。

    大模型每次出题给知识点起的名字可能略有出入，会以不同 id 落库，
    这里按名称归一化合并，避免进度页出现「同一个知识点既是熟练又是薄弱」。

    跑过语义聚类后按 canonical_id 分组，能进一步合并
    「Transformer的起源 / Transformer 定义与起源 / Transformer 的定义与起源」这类同义写法。
    """
    rows = (
        s.query(
            QuizQuestion.knowledge_point_id,
            func.count(QuizAnswer.id),
            func.avg(QuizAnswer.score),
        )
        .join(QuizAnswer, QuizAnswer.question_id == QuizQuestion.id)
        .filter(QuizQuestion.knowledge_point_id.isnot(None))
        .group_by(QuizQuestion.knowledge_point_id)
        .all()
    )
    merged = {}
    for kp_id, cnt, avg_score in rows:
        kp = s.get(KnowledgePoint, kp_id)
        raw_name = (kp.name if kp and kp.name else None) or kp_id
        if kp:
            name, group_id = canonical_name(s, kp)
        else:
            name, group_id = raw_name, kp_id
        key = _kp_group_key(kp, group_id)
        item = merged.setdefault(
            key,
            {"knowledgePointId": group_id, "name": name,
             "questionCount": 0, "_weighted": 0.0},
        )
        # 题量多的那条保留其 id，方便前端定位
        if cnt > item["questionCount"]:
            item["knowledgePointId"] = group_id
        item["questionCount"] += cnt
        item["_weighted"] += float(avg_score or 0) * cnt

    out = []
    for item in merged.values():
        cnt = item["questionCount"]
        mastery = round(item["_weighted"] / cnt, 3) if cnt else 0.0
        out.append(
            {
                "knowledgePointId": item["knowledgePointId"],
                "name": item["name"],
                "mastery": mastery,
                "level": _level(mastery),
                "questionCount": cnt,
            }
        )
    out.sort(key=lambda x: x["mastery"], reverse=True)
    return out


def _material_mastery_map(s):
    """每份资料的掌握度：该资料来源题目的平均得分。"""
    rows = (
        s.query(QuizQuestion.source_material_id, func.avg(QuizAnswer.score))
        .join(QuizAnswer, QuizAnswer.question_id == QuizQuestion.id)
        .filter(QuizQuestion.source_material_id.isnot(None))
        .group_by(QuizQuestion.source_material_id)
        .all()
    )
    return {mid: round(float(avg or 0), 3) for mid, avg in rows}


def _weak_points(s, limit=3):
    """薄弱知识点：错题按知识点聚类，TOP N，并给出复习建议。"""
    rows = (
        s.query(
            ErrorBook.knowledge_point_id,
            func.count(ErrorBook.id),
            func.avg(ErrorBook.score),
            ErrorBook.source_material_id,
            ErrorBook.source_page_number,
        )
        .filter(ErrorBook.knowledge_point_id.isnot(None))
        .group_by(
            ErrorBook.knowledge_point_id,
            ErrorBook.source_material_id,
            ErrorBook.source_page_number,
        )
        .all()
    )
    agg = {}
    for kp_id, cnt, avg_score, mid, page in rows:
        kp = s.get(KnowledgePoint, kp_id)
        if kp:
            name, group_id = canonical_name(s, kp)
        else:
            name, group_id = kp_id, kp_id
        key = _kp_group_key(kp, group_id)
        item = agg.setdefault(
            key, {"knowledgePoint": name, "errorCount": 0, "accuracy": 0.0}
        )
        item["errorCount"] += cnt
        item["accuracy"] = round(float(avg_score or 0), 3)
        # 资料已被删除时不要回落到 ID（用户会看到《mat_xxx》这种内部编号）
        if mid and "suggestedReview" not in item:
            mat = s.get(Material, mid)
            if mat:
                title = mat.title
                item["suggestedReview"] = (
                    f"重读《{title}》第{page}页" if page else f"重读《{title}》"
                )
    out = list(agg.values())
    out.sort(key=lambda x: x["errorCount"], reverse=True)
    for item in out:
        item.setdefault("suggestedReview", "建议重新阅读相关资料")
    return out[:limit]


def _week_range():
    today = date.today()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


@bp.get("/overview")
def overview():
    """P-01/P-02/P-03 学习进度总览：时长、资料覆盖、测验正确率 + 知识点掌握度 + 薄弱点。"""
    week_start, week_end = _week_range()
    with _session()() as s:
        total_materials = s.query(func.count(Material.id)).scalar() or 0
        total_chunks = s.query(func.count(MaterialChunk.id)).scalar() or 0
        covered_chunks = (
            s.query(func.count(MaterialChunk.id))
            .join(Material, MaterialChunk.material_id == Material.id)
            .filter(Material.status == "ready")
            .scalar()
            or 0
        )
        coverage_rate = round(covered_chunks / total_chunks, 3) if total_chunks else 0.0

        total_quiz_count = s.query(func.count(QuizSubmission.id)).scalar() or 0
        avg_accuracy = (
            round(float(s.query(func.avg(QuizSubmission.accuracy)).scalar() or 0), 3)
        )
        # 主指标用答题数（硬数据），不再显示推算出来的学习时长
        total_question_count = tracking.question_count(s)
        week_question_count = tracking.question_count(s, week_start, week_end)

        last_candidates = [
            v
            for v in (
                s.query(func.max(QuizSubmission.submitted_at)).scalar(),
                s.query(func.max(ChatMessage.created_at)).scalar(),
                s.query(func.max(Material.created_at)).scalar(),
            )
            if v
        ]
        last_study_at = max(last_candidates).isoformat() if last_candidates else None
        streak_days = tracking.streak_days(s)

        _maybe_merge(s)
        knowledge_points = _knowledge_mastery(s)
        mastery_map = _material_mastery_map(s)
        weak_points = _weak_points(s)

        materials = (
            s.query(Material).order_by(Material.created_at.desc()).all()
        )
        material_list = []
        for m in materials:
            note = (
                s.query(MaterialNote)
                .filter(MaterialNote.material_id == m.id)
                .first()
            )
            material_list.append(
                {
                    "materialId": m.id,
                    "title": m.title,
                    "fileType": _norm_type(m.file_type or ""),
                    "chunkCount": m.chunk_count or 0,
                    "mastery": mastery_map.get(m.id, 0.0),
                    "note": {
                        "content": note.content if note else "",
                        "contentLength": note.content_length if note else 0,
                    },
                }
            )

        mastered_materials = sum(
            1 for m in material_list if m["mastery"] >= 0.8
        )

    return ok(
        data={
            # PRD 总览字段
            "totalMaterials": total_materials,
            "totalChunks": total_chunks,
            "coveredChunks": covered_chunks,
            "coverageRate": coverage_rate,
            "totalQuizCount": total_quiz_count,
            "avgAccuracy": avg_accuracy,
            "totalQuestionCount": int(total_question_count),
            "weekQuestionCount": int(week_question_count),
            "currentStreakDays": streak_days,
            "lastStudyAt": last_study_at,
            # 前端进度页所需
            "masteredMaterials": mastered_materials,
            "weakPointsCount": len(weak_points),
            "knowledgePoints": knowledge_points,
            "materials": material_list,
            "weakPoints": weak_points,
        }
    )


@bp.get("/knowledge")
def knowledge():
    """知识点掌握度列表。"""
    with _session()() as s:
        points = _knowledge_mastery(s)
    return ok(data={"total": len(points), "list": points})


@bp.post("/knowledge/merge")
def knowledge_merge():
    """手动跑一次知识点语义聚类。

    ?dryRun=1  只返回建议，不写库（用来先看要合并哪些）
    ?threshold=0.86  相似度阈值

    这个操作会改变知识点命名与掌握度聚合结果，所以同时提供 reset 回滚。
    """
    try:
        threshold = float(request.args.get("threshold") or DEFAULT_THRESHOLD)
    except (TypeError, ValueError):
        return fail(msg="threshold 必须是数字", code=400)
    threshold = max(0.5, min(0.99, threshold))
    dry_run = (request.args.get("dryRun") or "").lower() in ("1", "true", "yes")

    try:
        with _session()() as s:
            res = merge_knowledge_points(s, threshold=threshold, dry_run=dry_run)
            if not dry_run:
                s.commit()
    except Exception as exc:
        current_app.logger.warning("知识点聚类失败：%s", exc)
        return fail(msg=f"聚类失败：{exc}", code=500)

    return ok(
        data=res,
        msg=("（dry run，未写库）" if dry_run else f"已合并：{res['total']} 行 → {res['groups']} 组"),
    )


@bp.post("/knowledge/merge/reset")
def knowledge_merge_reset():
    """清空聚类结果，回滚到「按名称归一化」的旧行为。"""
    with _session()() as s:
        n = reset_canonical(s)
        s.commit()
    return ok(data={"reset": n}, msg=f"已清除 {n} 行的聚类结果")


@bp.get("/sessions")
def sessions():
    """P-04 学习行为明细：按天倒序，返回当天答了几题 / 聊没聊 / 传没传资料。

    这里不给「学习时长」——那个数字是推算的，不可验证。
    """
    try:
        limit = int(request.args.get("limit", 30))
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 365))

    with _session()() as s:
        list_data = tracking.daily_detail(s, limit)
        total = len(tracking.activity_days(s))
    return ok(data={"total": total, "list": list_data})


@bp.get("/trends")
def trends():
    """P-05 正确率趋势：按自然周聚合测验正确率，默认最近 8 周。"""
    metric = request.args.get("metric") or "accuracy"
    granularity = request.args.get("granularity") or "week"
    try:
        limit = int(request.args.get("weeks", 8))
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 52))

    with _session()() as s:
        rows = (
            s.query(QuizSubmission.submitted_at, QuizSubmission.accuracy)
            .filter(QuizSubmission.submitted_at.isnot(None))
            .all()
        )

    # 按「周一」归桶，再求周平均正确率
    buckets = {}
    for submitted_at, acc in rows:
        day = submitted_at.date()
        monday = day - timedelta(days=day.weekday())
        buckets.setdefault(monday, []).append(float(acc or 0))

    this_monday = date.today() - timedelta(days=date.today().weekday())
    points = []
    for i in range(limit - 1, -1, -1):
        monday = this_monday - timedelta(weeks=i)
        vals = buckets.get(monday)
        points.append(
            {
                "label": monday.strftime("%m-%d"),
                "value": round(sum(vals) / len(vals), 3) if vals else 0.0,
                "hasData": bool(vals),
            }
        )
    return ok(data={"metric": metric, "granularity": granularity, "points": points})
