import json
from datetime import date, timedelta
from urllib.parse import quote

from flask import Blueprint, request, current_app, Response
from sqlalchemy import func

from utils.response import ok, fail
from utils.idgen import gen_id
from utils.json_util import extract_json
from models.report import WeeklyReport
from models.material import Material, MaterialChunk
from models.quiz import QuizSubmission
from models.knowledge import KnowledgePoint, ErrorBook
from services import tracking
from services.clients import llm_client
from services.prompts import PROMPT_REPORT
from services import exporters
# 复用进度模块的薄弱点聚类（含复习建议），保证两处口径一致
from routes.progress import _weak_points

bp = Blueprint("report", __name__, url_prefix="/api/report")


def _session():
    return current_app.SessionLocal


def _week_range(week_start_str, week_end_str=None):
    """解析周期（默认本周一 ~ 本周日）。

    若显式传了 weekEnd，则按 [weekStart, weekEnd] 原样使用（前端自定义区间）。
    """
    if week_start_str:
        start = date.fromisoformat(week_start_str)
        if week_end_str:
            end = date.fromisoformat(week_end_str)
            if end < start:
                raise ValueError("weekEnd 不能早于 weekStart")
            return start, end
        return start, start + timedelta(days=6)
    today = date.today()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def _count_questions(s, start, end):
    """某时间范围内的答题数（按测评提交日归属）。

    这是硬数据：每答一题落一条 quiz_answers，不需要任何折算。
    """
    return tracking.question_count(s, start, end)


def _avg_accuracy(s, start, end):
    """统计某时间范围内的平均正确率。"""
    row = (
        s.query(func.avg(QuizSubmission.accuracy))
        .filter(QuizSubmission.submitted_at >= start)
        .filter(QuizSubmission.submitted_at < end + timedelta(days=1))
        .scalar()
    )
    return round(float(row), 3) if row is not None else 0.0


def _collect_week_data(s, start, end):
    """从数据库聚合本周真实数据（R-02 各项指标）。"""
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)

    questions_this = _count_questions(s, start, end)
    questions_last = _count_questions(s, prev_start, prev_end)
    if questions_last > 0:
        questions_change = round((questions_this - questions_last) / questions_last, 3)
    else:
        questions_change = 0.0
    new_materials = (
        s.query(func.count(Material.id))
        .filter(Material.created_at >= start)
        .filter(Material.created_at < end + timedelta(days=1))
        .scalar()
        or 0
    )
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

    accuracy_this = _avg_accuracy(s, start, end)
    accuracy_last = _avg_accuracy(s, start - timedelta(days=7), end - timedelta(days=7))
    if accuracy_last > 0:
        accuracy_change = round((accuracy_this - accuracy_last) / accuracy_last, 3)
    else:
        accuracy_change = 0.0

    # 薄弱知识点：按知识点聚类本期错题，并给出复习建议（前端报告页会展示）
    rows = (
        s.query(
            ErrorBook.knowledge_point_id,
            func.count(ErrorBook.id).label("cnt"),
            func.avg(ErrorBook.score).label("avg_score"),
            ErrorBook.source_material_id,
            ErrorBook.source_page_number,
        )
        .filter(ErrorBook.knowledge_point_id.isnot(None))
        .filter(ErrorBook.created_at >= start)
        .filter(ErrorBook.created_at < end + timedelta(days=1))
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
        name = kp.name if kp else kp_id
        item = agg.setdefault(
            name, {"knowledgePoint": name, "errorCount": 0, "accuracy": 0.0}
        )
        item["errorCount"] += cnt
        item["accuracy"] = round(float(avg_score or 0), 3)
        if mid and "suggestedReview" not in item:
            mat = s.get(Material, mid)
            title = mat.title if mat else mid
            item["suggestedReview"] = (
                f"重读《{title}》第{page}页" if page else f"重读《{title}》"
            )
    weak_points = list(agg.values())
    weak_points.sort(key=lambda x: x["errorCount"], reverse=True)
    for item in weak_points:
        item.setdefault("suggestedReview", "建议重新阅读相关资料")

    return {
        "question_count": int(questions_this),
        "question_count_last": int(questions_last),
        "question_change": questions_change,
        "new_materials": int(new_materials),
        "total_materials": int(total_materials),
        "total_chunks": int(total_chunks),
        "covered_chunks": int(covered_chunks),
        "coverage_rate": coverage_rate,
        "accuracy_this": accuracy_this,
        "accuracy_last": accuracy_last,
        "accuracy_change": accuracy_change,
        "weak_points": weak_points[:3],
    }


@bp.post("/generate")
def generate():
    """R-01 周报生成：聚合本周数据 → 交给大模型撰写文字部分 → 落库。"""
    body = request.get_json(silent=True) or {}
    try:
        start, end = _week_range(body.get("weekStart"), body.get("weekEnd"))
    except ValueError:
        return fail("weekStart / weekEnd 格式应为 ISO 日期，如 2026-10-06", code=400)

    with _session()() as s:
        data = _collect_week_data(s, start, end)

        # 本期没有错题时退回全库口径，避免周报薄弱点永远为空
        if not data["weak_points"]:
            data["weak_points"] = _weak_points(s, limit=3)

        user_prompt = (
            "以下是用户本周的学习数据，请据此生成周报的文字部分。\n\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}\n\n"
            "注意：严格使用上述数据中的数值，不要编造。"
        )
        try:
            raw = llm_client.complete(
                [
                    {"role": "system", "content": PROMPT_REPORT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
            )
            ai = extract_json(raw)
        except Exception as e:
            return fail(f"周报生成失败：{e}", code=500)

        if not isinstance(ai, dict):
            return fail("周报生成失败：模型返回格式不正确", code=500)

        next_plan = ai.get("nextWeekPlan") or []
        motivation = ai.get("motivation") or "继续保持节奏，下周更好！"

        report_id = gen_id("rpt")
        # 同一周重复生成则覆盖
        existing = (
            s.query(WeeklyReport)
            .filter(WeeklyReport.week_start == start, WeeklyReport.week_end == end)
            .first()
        )
        row = existing or WeeklyReport(id=report_id)
        row.week_start = start
        row.week_end = end
        row.question_count = data["question_count"]
        row.question_count_last = data["question_count_last"]
        row.new_materials = data["new_materials"]
        row.covered_chunks = data["covered_chunks"]
        row.coverage_rate = data["coverage_rate"]
        row.accuracy_this_week = data["accuracy_this"]
        row.accuracy_last_week = data["accuracy_last"]
        row.accuracy_change = data["accuracy_change"]
        row.weak_points = data["weak_points"]
        row.next_week_plan = next_plan
        row.motivation = motivation
        if not existing:
            s.add(row)
        s.commit()
        created = row.created_at.isoformat() if row.created_at else None
        final_id = row.id

    return ok(
        data={
            "reportId": final_id,
            "weekStart": start.isoformat(),
            "weekEnd": end.isoformat(),
            "sections": {
                "questionCount": {
                    "thisWeek": data["question_count"],
                    "lastWeek": data["question_count_last"],
                    "changePercent": data["question_change"],
                    "summary": ai.get("questionSummary"),
                },
                "materialCoverage": {
                    "newMaterials": data["new_materials"],
                    "coveredChunks": data["covered_chunks"],
                    "coverageRate": data["coverage_rate"],
                    "summary": ai.get("coverageSummary"),
                },
                "accuracyTrend": {
                    "thisWeek": data["accuracy_this"],
                    "lastWeek": data["accuracy_last"],
                    "changePercent": data["accuracy_change"],
                    "summary": ai.get("accuracySummary"),
                },
                "weakPoints": data["weak_points"],
                "nextWeekPlan": next_plan,
                "motivation": motivation,
            },
            "createdAt": created,
        }
    )


@bp.get("/latest")
def latest():
    # R-01 最新一期周报
    with _session()() as s:
        row = (
            s.query(WeeklyReport)
            .order_by(WeeklyReport.week_start.desc())
            .first()
        )
        if not row:
            return ok(data=None)
        return ok(data=_report_payload(row, s))


@bp.get("/history")
def history():
    # R-03 周报历史列表
    page = max(1, int(request.args.get("page", 1)))
    page_size = max(1, int(request.args.get("pageSize", 20)))
    with _session()() as s:
        q = s.query(WeeklyReport)
        total = q.count()
        rows = (
            q.order_by(WeeklyReport.week_start.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        list_data = [
            {
                "reportId": r.id,
                "weekStart": r.week_start.isoformat(),
                "weekEnd": r.week_end.isoformat(),
                "questionCount": r.question_count or 0,
                "accuracy": float(r.accuracy_this_week or 0),
                "weakPointCount": len(r.weak_points or []),
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return ok(data={"total": total, "list": list_data})


def _report_doc(row, s=None):
    """把周报渲染成结构化文档，供 Markdown / Word / PDF 三种导出共用。

    三种格式共用这一份结构，避免「Markdown 改了、Word 没跟着改」。
    """
    sec = _report_payload(row, s)["sections"]
    qc = sec["questionCount"]
    mc = sec["materialCoverage"]
    at = sec["accuracyTrend"]

    blocks = [
        {"type": "h2", "text": "做题量"},
        {
            "type": "p",
            "text": (
                f"本周共答 {qc['thisWeek']} 题，较上周"
                f"{'上升' if qc['changePercent'] >= 0 else '下降'} "
                f"{round(abs(qc['changePercent']) * 100)}%（上周 {qc['lastWeek']} 题）。"
            ),
        },
        {"type": "h2", "text": "资料覆盖"},
        {
            "type": "p",
            "text": (
                f"新增资料 {mc['newMaterials']} 份，覆盖 {mc['coveredChunks']} 个知识块"
                f"（覆盖率 {round(mc['coverageRate'] * 100)}%）。"
            ),
        },
        {"type": "h2", "text": "正确率趋势"},
        {
            "type": "p",
            "text": (
                f"本周 {round(at['thisWeek'] * 100)}%，上周 {round(at['lastWeek'] * 100)}%，"
                f"{'上升' if at['changePercent'] >= 0 else '下降'} "
                f"{round(abs(at['changePercent']) * 100)}%。"
            ),
        },
        {"type": "h2", "text": f"薄弱知识点 TOP{len(sec['weakPoints'])}"},
        {
            "type": "ol",
            "items": [
                f"**{w['knowledgePoint']}**（错 {w['errorCount']} 次）"
                f" —— 建议：{w.get('suggestedReview', '重新阅读相关资料')}"
                for w in sec["weakPoints"]
            ],
        },
        {"type": "h2", "text": "下周计划"},
        {"type": "ol", "items": list(sec["nextWeekPlan"] or [])},
        {"type": "h2", "text": "一句话"},
        {"type": "quote", "text": sec["motivation"] or ""},
    ]
    return {"title": f"学习周报（{row.week_start} ~ {row.week_end}）", "blocks": blocks}


def _to_markdown(row, s=None):
    """把周报渲染为 Markdown（保留旧函数名，测试与早期调用方还在用）。"""
    return exporters.to_markdown(_report_doc(row, s))


# 导出格式表：format -> (mimetype, 扩展名, 渲染函数)
DOWNLOAD_FORMATS = {
    "md": (
        "text/markdown",
        "md",
        lambda doc: exporters.to_markdown(doc).encode("utf-8"),
    ),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
        exporters.to_docx,
    ),
    "pdf": ("application/pdf", "pdf", exporters.to_pdf),
}


@bp.get("/<report_id>/download")
def download(report_id):
    """周报下载：Markdown / Word / PDF，用 ?format=md|docx|pdf 选择（默认 md）。"""
    fmt = (request.args.get("format") or "md").strip().lower()
    if fmt not in DOWNLOAD_FORMATS:
        return fail("format 只支持 md / docx / pdf", code=400)

    with _session()() as s:
        row = s.get(WeeklyReport, report_id)
        if not row:
            return fail("周报不存在", code=404)
        doc = _report_doc(row, s)

    mimetype, ext, renderer = DOWNLOAD_FORMATS[fmt]
    try:
        payload = renderer(doc)
    except ImportError as e:
        return fail(f"导出 {ext} 缺少依赖（{e.name}），请先 pip install -r requirements.txt", code=500)
    except Exception as e:
        return fail(f"导出 {ext} 失败：{e}", code=500)

    filename = f"学习周报_{row.week_start}_{row.week_end}.{ext}"
    return Response(
        payload,
        mimetype=mimetype,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)
        },
    )


@bp.get("/<report_id>")
def get_report(report_id):
    # R-01 指定周报详情
    with _session()() as s:
        row = s.get(WeeklyReport, report_id)
        if not row:
            return fail("周报不存在", code=404)
        return ok(data=_report_payload(row, s))


def _question_change(row):
    """做题量环比：直接用本期存的「上周答题数」算，不再依赖上期周报快照。

    早期版本是拿上一期周报记录的数值来比——中间没生成周报就会失真。
    现在生成时就按真实日期区间统计好上周答题数存下来，环比永远准确。
    """
    last = row.question_count_last or 0
    this = row.question_count or 0
    if last <= 0:
        return 0.0
    return round((this - last) / last, 3)


def _report_payload(row, s=None):
    """把周报记录转为 PRD 返回结构。

    s 参数保留只是为了兼容既有调用签名（环比已改为读本记录的 question_count_last）。
    """
    return {
        "reportId": row.id,
        "weekStart": row.week_start.isoformat(),
        "weekEnd": row.week_end.isoformat(),
        "sections": {
            "questionCount": {
                "thisWeek": row.question_count or 0,
                "lastWeek": row.question_count_last or 0,
                "changePercent": _question_change(row),
            },
            "materialCoverage": {
                "newMaterials": row.new_materials,
                "coveredChunks": row.covered_chunks,
                "coverageRate": float(row.coverage_rate or 0),
            },
            "accuracyTrend": {
                "thisWeek": float(row.accuracy_this_week or 0),
                "lastWeek": float(row.accuracy_last_week or 0),
                "changePercent": float(row.accuracy_change or 0),
            },
            "weakPoints": row.weak_points or [],
            "nextWeekPlan": row.next_week_plan or [],
            "motivation": row.motivation,
        },
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }
