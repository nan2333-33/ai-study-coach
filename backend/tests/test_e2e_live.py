"""端到端闭环验证（真实调用大模型与向量模型，会产生少量费用）。

覆盖：上传资料 → 解析入库 → RAG 对话 → 自动出题 → 提交批改 → 进度 → AI 周报 → 清理

用法（先确保后端已启动）：
    python tests/test_e2e_live.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

BASE = "http://127.0.0.1:5000"
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "RAG学习笔记.md")

step = 0
failures = []


def head(text):
    global step
    step += 1
    print(f"\n【{step}】{text}")
    print("-" * 60)


def good(text):
    print(f"    ✓ {text}")


def bad(text):
    print(f"    ✗ {text}")
    failures.append(text)


def call(method, path, **kw):
    r = getattr(requests, method)(BASE + path, timeout=180, **kw)
    try:
        body = r.json()
    except Exception:
        return r.status_code, None, r.text[:200]
    return r.status_code, body, ""


def expect_ok(status, body, raw, what):
    if status != 200 or not body or body.get("code") != 0:
        bad(f"{what} 失败：HTTP {status} code={body and body.get('code')} "
            f"msg={body and body.get('msg')} {raw}")
        return None
    good(f"{what} 成功")
    return body["data"]


def main():
    if not os.path.exists(FIXTURE):
        print(f"找不到测试资料：{FIXTURE}")
        return 1

    # ---------- 1. 上传 ----------
    head("上传资料（Markdown）")
    with open(FIXTURE, "rb") as f:
        st, body, raw = call("post", "/api/materials/upload",
                             files={"file": (os.path.basename(FIXTURE), f, "text/markdown")},
                             data={"title": "RAG 学习笔记"})
    data = expect_ok(st, body, raw, "上传")
    if not data:
        return 1
    mid = data.get("materialId") or data.get("id")
    print(f"    资料 ID: {mid}")

    # ---------- 2. 等解析 ----------
    head("等待解析（读文字 → 语义切块 → 向量化 → 入库）")
    ready = False
    for i in range(40):
        time.sleep(3)
        st, body, raw = call("get", f"/api/materials/{mid}")
        d = (body or {}).get("data") or {}
        status = d.get("status")
        print(f"    第 {i+1} 次查询：status={status}")
        if status == "ready":
            ready = True
            good(f"解析完成，切出 {d.get('chunkCount')} 个片段")
            break
        if status == "error":
            bad(f"解析失败：{d.get('errorMessage')}")
            return 1
    if not ready:
        bad("等待 120 秒仍未解析完成")
        return 1

    # ---------- 3. RAG 对话 ----------
    head("问一问（RAG 检索 + 大模型回答 + 来源引用）")
    st, body, raw = call("post", "/api/chat/sessions", json={"materialIds": [mid]})
    d = expect_ok(st, body, raw, "创建会话")
    if not d:
        return 1
    sid = d["sessionId"]

    question = "这份资料里，余弦相似度的下限设的是多少？低于它的检索结果怎么处理？"
    print(f"    提问：{question}")
    st, body, raw = call("post", f"/api/chat/sessions/{sid}/messages",
                         json={"message": question})
    d = expect_ok(st, body, raw, "发送消息")
    if d:
        answer = (d.get("answer") or d.get("content") or "").strip()
        sources = d.get("sources") or []
        print(f"    回答：{answer[:220]}")
        good(f"命中 {len(sources)} 个来源片段")
        if sources:
            s0 = sources[0]
            print(f"    来源1：{s0.get('materialTitle') or s0.get('title')} "
                  f"(相关度 {s0.get('score')})")
        if "0.15" in answer:
            good("答案中正确引用了资料里的数值 0.15 → RAG 检索生效")
        else:
            bad("回答里没出现 0.15，可能没有真正检索到资料内容")

    # ---------- 4. 出题 ----------
    head("做测评（大模型自动出题）")
    st, body, raw = call("post", "/api/quiz/generate",
                         json={"materialIds": [mid], "questionCount": 4,
                               "difficulty": "mixed"})
    d = expect_ok(st, body, raw, "生成测验")
    if not d:
        return 1
    qid = d.get("quizId")
    questions = d.get("questions") or []
    print(f"    测验 ID: {qid}，共 {len(questions)} 题")
    types = {}
    for q in questions:
        types[q.get("type")] = types.get(q.get("type"), 0) + 1
        opts = q.get("options") or {}
        print(f"      [{q.get('type')}] {q.get('content') or q.get('question')}")
        if opts:
            print(f"         选项: {opts}")
    good(f"题型分布：{types}")
    for q in questions:
        if q.get("type") == "judgment" and q.get("options") != {"A": "正确", "B": "错误"}:
            bad(f"判断题选项不是 A正确/B错误：{q.get('options')}")
            break
    else:
        good("判断题选项符合约定（A:正确 / B:错误）")

    # ---------- 5. 提交批改 ----------
    head("提交答案（选择判断精确比对 + 简答题大模型改卷）")
    answers = []
    for q in questions:
        t = q.get("type")
        if t == "judgment":
            answers.append({"questionId": q["questionId"] or q["id"], "answer": "A"})
        elif t == "choice":
            answers.append({"questionId": q["questionId"] or q["id"], "answer": "A"})
        else:
            answers.append({
                "questionId": q["questionId"] or q["id"],
                "answer": "先检索资料片段，再把片段作为上下文拼进提示词交给大模型生成答案。",
            })
    st, body, raw = call("post", f"/api/quiz/{qid}/submit",
                         json={"answers": answers, "durationMinutes": 6})
    d = expect_ok(st, body, raw, "提交批改")
    if d:
        results = d.get("results") or []
        correct = sum(1 for r in results if r.get("isCorrect"))
        print(f"    得分：{d.get('totalScore')}/{d.get('maxScore')}  "
              f"正确率 {d.get('accuracy')}  答对 {correct} 题")
        if len(results) == len(questions):
            good(f"批改结果数量与题数一致（{len(results)} 题）")
        else:
            bad(f"批改结果数量对不上：{len(results)} != {len(questions)}")
        sa = [r for r in results if r.get("type") == "shortAnswer"]
        if sa and (sa[0].get("explanation") or sa[0].get("referenceAnswer")):
            good("简答题由大模型改卷并给出评语（改卷能力生效）")
        elif sa:
            bad("简答题没有评语")

    # ---------- 6. 查看结果 ----------
    head("查看测评结果")
    st, body, raw = call("get", f"/api/quiz/{qid}/result")
    d = expect_ok(st, body, raw, "获取结果")
    if d:
        for r in (d.get("results") or d.get("questions") or [])[:4]:
            print(f"      {r.get('type')} | 你的答案 {r.get('userAnswer')} | "
                  f"正确 {r.get('correctAnswer')} | {'对' if r.get('isCorrect') else '错'}")

    # ---------- 7. 进度 ----------
    head("看进度")
    st, body, raw = call("get", "/api/progress/overview")
    d = expect_ok(st, body, raw, "进度总览")
    if d:
        print(f"    {d}")
    st, body, raw = call("get", "/api/progress/trends")
    d = expect_ok(st, body, raw, "进度趋势")
    if d:
        pts = d.get("points") or []
        print(f"    趋势点数：{len(pts)}，最新：{pts[-1] if pts else '无'}")

    # ---------- 8. 周报 ----------
    head("出周报（大模型撰写）")
    st, body, raw = call("post", "/api/report/generate", json={})
    d = expect_ok(st, body, raw, "生成周报")
    if d:
        rid = d.get("reportId") or d.get("id")
        print(f"    周报 ID: {rid}")
        st2, body2, raw2 = call("get", f"/api/report/{rid}")
        d2 = (body2 or {}).get("data") or {}
        s = d2.get("sections") or {}
        qc = s.get("questionCount") or {}
        at = s.get("accuracyTrend") or {}
        mc = s.get("materialCoverage") or {}
        wps = s.get("weakPoints") or []
        plan = s.get("nextWeekPlan") or []
        print(f"    周期：{d2.get('weekStart')} ~ {d2.get('weekEnd')}")
        print(f"    做题量：本周 {qc.get('thisWeek')} 题（上周 {qc.get('lastWeek')} 题），环比 {qc.get('changePercent')}")
        print(f"    正确率：{at.get('thisWeek')}（上周 {at.get('lastWeek')}）")
        print(f"    资料覆盖：新增 {mc.get('newMaterials')} 份，"
              f"{mc.get('coveredChunks')} 个知识块，覆盖率 {mc.get('coverageRate')}")
        print(f"    薄弱点：{len(wps)} 个")
        for w in wps[:3]:
            print(f"      - {w.get('knowledgePoint')}（错 {w.get('errorCount')} 次）"
                  f" 建议：{w.get('suggestedReview')}")
        print(f"    下周计划：{len(plan)} 条")
        for p in plan[:2]:
            print(f"      · {p}")
        if s.get("motivation"):
            print(f"    一句话：{s.get('motivation')}")
        # 前端 app.js 按 r.sections 解析，这里核对关键字段是否齐全
        if qc.get("thisWeek") is not None and "changePercent" in qc:
            good("questionCount 字段齐全（前端不会显示 NaN）")
        else:
            bad(f"questionCount 字段缺失：{qc}")
        if wps and all(w.get("suggestedReview") for w in wps):
            good("薄弱点全部带复习建议")
        else:
            bad("薄弱点缺少 suggestedReview")
        if plan:
            good("生成了下周计划")
        else:
            bad("下周计划为空")

    # ---------- 9. 清理 ----------
    head("清理测试资料")
    st, body, raw = call("delete", f"/api/materials/{mid}")
    expect_ok(st, body, raw, "删除资料")

    print("\n" + "=" * 60)
    if failures:
        print(f"闭环验证完成，但有 {len(failures)} 项问题：")
        for f_ in failures:
            print(f"  - {f_}")
        return 1
    print("闭环验证全部通过：上传 → 解析 → 对话 → 出题 → 批改 → 进度 → 周报")
    return 0


if __name__ == "__main__":
    sys.exit(main())
