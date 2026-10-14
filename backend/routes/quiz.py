import json

from flask import Blueprint, request, current_app
from sqlalchemy import func

from utils.response import ok, fail
from utils.idgen import gen_id
from utils.json_util import extract_json_list
from models.quiz import Quiz, QuizQuestion, QuizSubmission, QuizAnswer
from models.material import Material, MaterialChunk
from models.knowledge import KnowledgePoint, ErrorBook
from services.clients import llm_client
from services.prompts import PROMPT_QUIZ_MAKER, PROMPT_GRADER, PROMPT_EXPLAINER

bp = Blueprint("quiz", __name__, url_prefix="/api/quiz")

VALID_TYPES = ("choice", "judgment", "shortAnswer")
# 默认题型配比：判断 1/4 + 选择 1/2 + 简答 1/4
DEFAULT_RATIO = {"judgment": 0.25, "choice": 0.5, "shortAnswer": 0.25}
# 判断题选项是固定二选一，前后端约定死，不让模型自由发挥
JUDGMENT_OPTIONS = {"A": "正确", "B": "错误"}


def _session():
    return current_app.SessionLocal


def _norm_judgment(v):
    """把各种判断题答案写法统一成 A/B。

    兼容模型输出（true/false/A/B）与前端表单值（A/B），
    无法识别时返回 None（视为未作答）。
    """
    s = str(v or "").strip().lower()
    if s in ("a", "true", "1", "yes", "t", "对", "正确", "right"):
        return "A"
    if s in ("b", "false", "0", "no", "f", "错", "错误", "wrong"):
        return "B"
    return None


def _norm_options(options):
    """把模型可能返回的各种 options 形态统一成 {键: 文本} 对象。

    模型偶尔会给出数组（["A. xxx", ...]）或 JSON 字符串，这里一律兜住。
    """
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except (ValueError, TypeError):
            return None
    if isinstance(options, dict) and options:
        return {str(k): str(v) for k, v in options.items()}
    if isinstance(options, list) and options:
        out = {}
        letters = "ABCDEFGH"
        for i, item in enumerate(options):
            key = letters[i] if i < len(letters) else str(i + 1)
            out[key] = item if isinstance(item, str) else str(item)
        return out
    return None


def _split_counts(total, ratio):
    """按配比拆分题型数量，保证总和为 total，且题数足够时三种题型都出现。"""
    r = {**DEFAULT_RATIO, **(ratio or {})}
    counts = {
        "judgment": int(round(total * float(r.get("judgment", 0.25)))),
        "choice": int(round(total * float(r.get("choice", 0.5)))),
        "shortAnswer": int(round(total * float(r.get("shortAnswer", 0.25)))),
    }
    # 修正到总数一致（误差补到选择题）
    counts["choice"] += total - sum(counts.values())
    # 题量足够时保证三种题型都有
    if total >= 3:
        for k in list(counts):
            if counts[k] == 0:
                donor = max(counts, key=counts.get)
                if counts[donor] > 1:
                    counts[donor] -= 1
                    counts[k] += 1
    return counts


def _load_material_text(s, material_ids):
    """取所选资料已处理完成的分块全文（出题依据）。"""
    chunks = (
        s.query(MaterialChunk)
        .filter(MaterialChunk.material_id.in_(material_ids))
        .order_by(MaterialChunk.material_id, MaterialChunk.chunk_index)
        .all()
    )
    if not chunks:
        return None
    parts = []
    for c in chunks:
        page = f"第{c.page_number}页" if c.page_number else "未知页码"
        parts.append(f"[资料 {c.material_id} {page}]\n{c.content}")
    return "\n\n".join(parts)


def _validate_question(q):
    """Q-02 题目质量校验：不符合规范的题目直接丢弃。"""
    if not isinstance(q, dict):
        return False
    t = q.get("type")
    if t not in VALID_TYPES:
        return False
    if not q.get("question"):
        return False
    if t == "choice":
        opts = _norm_options(q.get("options"))
        if not opts or len(opts) < 2:
            return False
        if str(q.get("correctAnswer")).strip().upper() not in opts:
            return False
    elif t == "judgment":
        # 判断题选项固定 A/B，只校验答案能否归一
        if _norm_judgment(q.get("correctAnswer")) is None:
            return False
    elif t == "shortAnswer":
        if not q.get("referenceAnswer"):
            return False
    return True


def _upsert_knowledge_point(s, name, material_id):
    """知识点按「名称 + 资料」去重后写入表9。"""
    if not name:
        return None
    kp = (
        s.query(KnowledgePoint)
        .filter(KnowledgePoint.name == name, KnowledgePoint.material_id == material_id)
        .first()
    )
    if kp:
        return kp.id
    kp = KnowledgePoint(id=gen_id("kp"), name=name, material_id=material_id)
    s.add(kp)
    s.flush()
    return kp.id


@bp.post("/generate")
def generate():
    """Q-01 自动出题：资料全文 → 出题官(提示词 B) → 校验 → 落库。"""
    body = request.get_json(silent=True) or {}
    material_ids = body.get("materialIds") or []
    if not material_ids:
        return fail("materialIds 不能为空", code=400)
    try:
        question_count = int(body.get("questionCount", 0))
    except (TypeError, ValueError):
        return fail("questionCount 必须为整数", code=400)
    if question_count <= 0:
        return fail("questionCount 必须大于 0", code=400)

    ratio = body.get("typeRatio")
    difficulty = body.get("difficulty") or "mixed"

    with _session()() as s:
        context = _load_material_text(s, material_ids)
        if not context:
            return fail("所选资料暂无可出题内容（可能还在处理中）", code=400)

        counts = _split_counts(question_count, ratio)
        default_mid = material_ids[0]

        user_prompt = (
            f"请根据以下学习资料，生成一套测验题。\n\n"
            f"【资料内容】\n{context}\n\n"
            f"【出题要求】\n"
            f"- 总题数：{question_count} 题\n"
            f"- 题型与数量：判断题 {counts['judgment']} 道、"
            f"选择题 {counts['choice']} 道、简答题 {counts['shortAnswer']} 道\n"
            f"- 难度：简单、中等、较难三种都要有，大致均匀搭配\n"
            f"- source.materialId 必须是 {material_ids} 之一；"
            f"pageNumber 填资料中的页码（无法判断填 0），chunkIndex 填 0 即可\n"
            f"- 严格按系统提示词规定的 JSON 数组输出"
        )

        try:
            raw = llm_client.complete(
                [
                    {"role": "system", "content": PROMPT_QUIZ_MAKER},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
            )
            questions = extract_json_list(raw)
        except Exception as e:
            return fail(f"出题失败：{e}", code=500)

        # Q-02 质量校验
        questions = [q for q in questions if _validate_question(q)]
        if not questions:
            return fail("生成的题目未通过质量校验，请重试", code=500)

        quiz_id = gen_id("quiz")
        quiz = Quiz(
            id=quiz_id,
            material_ids=material_ids,
            question_count=len(questions),
            type_ratio=ratio or DEFAULT_RATIO,
            difficulty=difficulty,
            status="ready",
        )
        s.add(quiz)

        question_data = []
        for idx, q in enumerate(questions):
            qid = gen_id("q")
            t = q["type"]
            src = q.get("source") or {}
            mid = src.get("materialId") if src.get("materialId") in material_ids else default_mid
            kp_id = _upsert_knowledge_point(s, q.get("knowledgePoint"), mid)

            correct_answer = ""
            options = None
            if t == "choice":
                options = _norm_options(q.get("options"))
                correct_answer = str(q["correctAnswer"]).strip().upper()
            elif t == "judgment":
                options = dict(JUDGMENT_OPTIONS)
                correct_answer = _norm_judgment(q.get("correctAnswer"))

            row = QuizQuestion(
                id=qid,
                quiz_id=quiz_id,
                type=t,
                question=q["question"],
                options=options,
                correct_answer=correct_answer,
                reference_answer=q.get("referenceAnswer") if t == "shortAnswer" else None,
                source_material_id=mid,
                source_page_number=src.get("pageNumber"),
                source_chunk_index=src.get("chunkIndex"),
                knowledge_point_id=kp_id,
                order_index=idx,
            )
            s.add(row)
            # 返回给前端的题目不包含答案（PRD：答案在提交后返回）
            item = {
                "questionId": qid,
                "type": t,
                "question": q["question"],
                "source": {
                    "materialId": mid,
                    "pageNumber": src.get("pageNumber"),
                    "chunkIndex": src.get("chunkIndex"),
                },
            }
            # 选择题与判断题都带 options 返回（判断题固定 A/B），前端统一渲染
            if options:
                item["options"] = options
            if q.get("knowledgePoint"):
                item["knowledgePoint"] = q["knowledgePoint"]
            question_data.append(item)

        s.commit()

    return ok(
        data={
            "quizId": quiz_id,
            "materialIds": material_ids,
            "status": "ready",
            "questions": question_data,
        }
    )


def _norm_choice(v):
    return str(v or "").strip().upper()


def _num(v):
    """数值归一：整数分显示为整数，0.5 之类保留小数。"""
    f = float(v or 0)
    return int(f) if f == int(f) else f


def _result_payload(s, submission):
    """按提交记录组装批改结果（提交后返回 与 查看结果 共用）。"""
    rows = (
        s.query(QuizAnswer, QuizQuestion)
        .join(QuizQuestion, QuizAnswer.question_id == QuizQuestion.id)
        .filter(QuizAnswer.submission_id == submission.id)
        .order_by(QuizQuestion.order_index, QuizQuestion.created_at, QuizQuestion.id)
        .all()
    )
    items = []
    for ans, q in rows:
        item = {
            "questionId": q.id,
            "type": q.type,
            # 带上题干：查看历史测评时前端手上没有题目原文，只能从结果里取
            "question": q.question,
            "userAnswer": ans.user_answer,
            "score": _num(ans.score),
            "explanation": ans.explanation,
        }
        if q.type == "shortAnswer":
            item["referenceAnswer"] = q.reference_answer
            item["isCorrect"] = bool(ans.is_correct)
        else:
            item["correctAnswer"] = q.correct_answer
            item["isCorrect"] = bool(ans.is_correct)
        if q.type == "judgment":
            # 统一成 A/B 返回，前端结果页才能直接和选项键比对
            item["correctAnswer"] = _norm_judgment(q.correct_answer) or "A"
            item["userAnswer"] = _norm_judgment(ans.user_answer) or ""
        if q.type in ("choice", "judgment"):
            item["options"] = _norm_options(q.options) or dict(JUDGMENT_OPTIONS)
        items.append(item)

    return {
        "submissionId": submission.id,
        "quizId": submission.quiz_id,
        "totalScore": _num(submission.total_score),
        "maxScore": _num(submission.max_score),
        "accuracy": float(submission.accuracy or 0),
        "results": items,
        "submittedAt": submission.submitted_at.isoformat()
        if submission.submitted_at
        else None,
    }


def _fill_objective_explanations(results):
    """给选择题 / 判断题补一句 AI 解析。

    改卷官提示词明确要求客观题"不给解释"，所以这两类的 explanation 一直是 None，
    结果页自然看不到解析。这里单独调一次模型补上。
    解析属于锦上添花：**失败就静默降级**，绝不能影响已经算好的成绩。
    """
    objs = [r for r in results if r["question"].type in ("choice", "judgment")]
    if not objs:
        return

    payload = []
    for r in objs:
        q = r["question"]
        if q.type == "judgment":
            correct = _norm_judgment(q.correct_answer) or "A"
            user = _norm_judgment(r["user_answer"]) or ""
        else:
            correct = q.correct_answer
            user = r["user_answer"]
        payload.append(
            {
                "questionId": q.id,
                "type": q.type,
                "question": q.question,
                "options": _norm_options(q.options) or dict(JUDGMENT_OPTIONS),
                "correctAnswer": correct,
                "userAnswer": user,
                "isCorrect": bool(r["is_correct"]),
            }
        )

    try:
        raw = llm_client.complete(
            [
                {"role": "system", "content": PROMPT_EXPLAINER},
                {
                    "role": "user",
                    "content": (
                        "请为以下题目各写一句解析，严格按 JSON 数组输出：\n\n"
                        + json.dumps(payload, ensure_ascii=False, indent=2)
                    ),
                },
            ],
            temperature=0.3,
        )
        items = extract_json_list(raw)
    except Exception:
        return

    mapping = {}
    for it in items:
        if isinstance(it, dict) and it.get("questionId") and it.get("explanation"):
            mapping[it["questionId"]] = str(it["explanation"]).strip()
    for r in objs:
        r["explanation"] = mapping.get(r["question"].id)


@bp.post("/<quiz_id>/submit")
def submit(quiz_id):
    """Q-04 自动批改：选择/判断精确比对；简答题交改卷官(提示词 C) 打分。"""
    body = request.get_json(silent=True) or {}
    answers = body.get("answers") or []
    if not answers:
        return fail("answers 不能为空", code=400)
    answer_map = {}
    for a in answers:
        if a.get("questionId"):
            answer_map[a["questionId"]] = a.get("answer")

    with _session()() as s:
        quiz = s.get(Quiz, quiz_id)
        if not quiz:
            return fail("测验不存在", code=404)
        # 必须按出题顺序取，否则批改结果的顺序会和卷面上的顺序对不上
        questions = (
            s.query(QuizQuestion)
            .filter(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.order_index, QuizQuestion.id)
            .all()
        )
        if not questions:
            return fail("该测验没有题目", code=400)

        results = []
        to_grade = []  # 需要交给改卷官的简答题

        for q in questions:
            user_answer = answer_map.get(q.id)
            if q.type == "choice":
                is_correct = _norm_choice(user_answer) == _norm_choice(q.correct_answer)
                score = 1 if is_correct else 0
                explanation = None
            elif q.type == "judgment":
                # 两边都归到 A/B 再比，兼容旧库里的 true/false
                is_correct = _norm_judgment(user_answer) == _norm_judgment(
                    q.correct_answer
                )
                score = 1 if is_correct else 0
                explanation = None
            else:
                # 简答题：统一交给改卷官打分
                is_correct = None
                score = 0
                explanation = None
                to_grade.append(q)

            results.append(
                {
                    "question": q,
                    "user_answer": user_answer or "",
                    "is_correct": is_correct,
                    "score": score,
                    "explanation": explanation,
                }
            )

        # 简答题批改：一次性提交给改卷官
        if to_grade:
            grade_items = []
            for q in to_grade:
                grade_items.append(
                    {
                        "questionId": q.id,
                        "type": "shortAnswer",
                        "question": q.question,
                        "userAnswer": (answer_map.get(q.id) or ""),
                        "referenceAnswer": q.reference_answer,
                    }
                )
            try:
                raw = llm_client.complete(
                    [
                        {"role": "system", "content": PROMPT_GRADER},
                        {
                            "role": "user",
                            "content": (
                                "请批改以下简答题，严格按 JSON 数组输出：\n\n"
                                + json.dumps(grade_items, ensure_ascii=False, indent=2)
                            ),
                        },
                    ],
                    temperature=0.2,
                )
                graded = extract_json_list(raw)
            except Exception as e:
                return fail(f"批改失败：{e}", code=500)

            graded_map = {}
            for g in graded:
                if isinstance(g, dict) and g.get("questionId"):
                    graded_map[g["questionId"]] = g

            for r in results:
                if r["question"].type != "shortAnswer":
                    continue
                g = graded_map.get(r["question"].id) or {}
                raw_score = float(g.get("score", 0) or 0)
                # 只允许 0 / 0.5 / 1 三档
                if raw_score >= 1:
                    r["score"] = 1
                elif raw_score >= 0.5:
                    r["score"] = 0.5
                else:
                    r["score"] = 0
                r["is_correct"] = r["score"] == 1
                r["explanation"] = g.get("explanation")

        # 选择题 / 判断题：让 AI 逐题写一句解析（改卷官对客观题不给解释，
        # 原来这两类题的 explanation 一直是 None，结果页就看不到解析了）
        _fill_objective_explanations(results)

        # 汇总得分
        max_score = len(results)
        total_score = sum(r["score"] for r in results)
        accuracy = round(total_score / max_score, 3) if max_score else 0

        submission_id = gen_id("sub")
        submission = QuizSubmission(
            id=submission_id,
            quiz_id=quiz_id,
            total_score=total_score,
            max_score=max_score,
            accuracy=accuracy,
            duration_minutes=body.get("durationMinutes"),
        )
        s.add(submission)

        # 落库答题明细 + 错题本（供周报薄弱点分析使用）
        for r in results:
            q = r["question"]
            s.add(
                QuizAnswer(
                    id=gen_id("ans"),
                    submission_id=submission_id,
                    question_id=q.id,
                    user_answer=r["user_answer"],
                    is_correct=(1 if r["is_correct"] else 0)
                    if r["is_correct"] is not None
                    else None,
                    score=r["score"],
                    explanation=r["explanation"],
                )
            )
            if r["score"] < 1:  # 未得满分 → 进入错题本
                s.add(
                    ErrorBook(
                        id=gen_id("err"),
                        question_id=q.id,
                        submission_id=submission_id,
                        user_answer=r["user_answer"],
                        reference_answer=q.reference_answer
                        or (q.correct_answer if q.type != "shortAnswer" else None),
                        score=r["score"],
                        knowledge_point_id=q.knowledge_point_id,
                        source_material_id=q.source_material_id,
                        source_page_number=q.source_page_number,
                        review_count=0,
                    )
                )

        s.commit()
        payload = _result_payload(s, submission)

    return ok(data=payload)


@bp.get("/submissions/<submission_id>")
def get_submission(submission_id):
    """回看某一次历史测评（按提交记录 id）。

    历史列表给的是 recordId（提交记录），可能同一套题提交过多次，
    所以按提交记录查比按 quiz 查更准确。
    """
    with _session()() as s:
        submission = s.get(QuizSubmission, submission_id)
        if not submission:
            return fail("提交记录不存在", code=404)
        return ok(data=_result_payload(s, submission))


@bp.get("/<quiz_id>/result")
def get_result(quiz_id):
    """查看结果（Q-05）：返回该测验最近一次提交的批改结果。"""
    with _session()() as s:
        if not s.get(Quiz, quiz_id):
            return fail("测验不存在", code=404)
        submission = (
            s.query(QuizSubmission)
            .filter(QuizSubmission.quiz_id == quiz_id)
            .order_by(QuizSubmission.submitted_at.desc())
            .first()
        )
        if not submission:
            return fail("该测验尚未提交", code=404)
        return ok(data=_result_payload(s, submission))


@bp.get("/history")
def quiz_history():
    """历史记录：按提交倒序列出历次测验成绩。"""
    page = max(1, int(request.args.get("page", 1)))
    page_size = max(1, int(request.args.get("pageSize", 20)))
    with _session()() as s:
        q = s.query(QuizSubmission)
        total = q.count()
        rows = (
            q.order_by(QuizSubmission.submitted_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        list_data = []
        for sub in rows:
            quiz = s.get(Quiz, sub.quiz_id)
            ids = (quiz.material_ids if quiz else None) or []
            titles = []
            for mid in ids:
                mat = s.get(Material, mid)
                if mat:
                    titles.append(mat.title)
            if len(titles) == 1:
                material = titles[0]
            elif len(titles) > 1:
                material = f"{titles[0]} 等 {len(titles)} 份"
            else:
                material = "—"
            list_data.append(
                {
                    "recordId": sub.id,
                    # 前端要靠 quizId 回看这套题的题目与解析
                    "quizId": sub.quiz_id,
                    "date": sub.submitted_at.date().isoformat()
                    if sub.submitted_at
                    else None,
                    "material": material,
                    "questionCount": quiz.question_count if quiz else 0,
                    "score": _num(sub.total_score),
                    "maxScore": _num(sub.max_score),
                    "accuracy": float(sub.accuracy or 0),
                    "durationSec": int((sub.duration_minutes or 0) * 60),
                }
            )
    return ok(data={"total": total, "list": list_data})


@bp.get("/errors")
def errors():
    # TODO: 错题本列表（Q-06）
    return ok(data={"total": 0, "list": []})


@bp.get("/weak-points")
def weak_points():
    """Q-07 薄弱知识点：按知识点聚类错题（供周报复用）。"""
    with _session()() as s:
        rows = (
            s.query(
                ErrorBook.knowledge_point_id,
                func.count(ErrorBook.id).label("cnt"),
                func.avg(ErrorBook.score).label("avg_score"),
            )
            .filter(ErrorBook.knowledge_point_id.isnot(None))
            .group_by(ErrorBook.knowledge_point_id)
            .all()
        )
        weak = []
        for kp_id, cnt, avg_score in rows:
            kp = s.get(KnowledgePoint, kp_id)
            name = kp.name if kp else kp_id
            weak.append(
                {
                    "knowledgePoint": name,
                    "errorCount": cnt,
                    "accuracy": round(float(avg_score or 0), 3),
                }
            )
        weak.sort(key=lambda x: x["errorCount"], reverse=True)
    return ok(data={"totalErrors": len(rows), "weakPoints": weak})


