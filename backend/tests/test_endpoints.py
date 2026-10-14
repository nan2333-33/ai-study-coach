"""新增接口验证：重新解析 / 查看结果 / 历史记录 / 总览统计 / 知识点掌握度 / 薄弱点 / 周报下载。

用 FakeLLM / FakeEmbedding 替代真实模型，不依赖任何 API Key。
运行：python tests/test_endpoints.py
"""
import json
import os
import sys
import tempfile
from datetime import date, datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

_TMP_DB = os.path.join(tempfile.gettempdir(), "ailms_ep_test.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DB_URL"] = "sqlite:///" + _TMP_DB

from app import create_app  # noqa: E402
from models.material import Material, MaterialChunk  # noqa: E402
from models.learning import LearningSession  # noqa: E402
from models.quiz import QuizAnswer, QuizSubmission  # noqa: E402  (备用：需要手工造答题数据时)

from services import clients  # noqa: E402
from services.prompts import (  # noqa: E402
    PROMPT_CHAT_TUTOR,
    PROMPT_QUIZ_MAKER,
    PROMPT_GRADER,
    PROMPT_REPORT,
)
from services.vector_store import vector_store  # noqa: E402
import routes.materials as materials_route  # noqa: E402

_PASSED = 0
_FAILED = 0


def check(name, cond):
    global _PASSED, _FAILED
    if cond:
        _PASSED += 1
        print(f"  [OK] {name}")
    else:
        _FAILED += 1
        print(f"  [FAIL] {name}")


# ---------------- 假模型 ----------------
def fake_vec(text):
    """造一个和 Config.EMBED_DIM 同维的假向量。

    维度必须跟着配置走：写死 16 维会被 Chroma 拒（collection 是按 EMBED_DIM 建的）。
    """
    import hashlib
    import math

    from config import Config

    dim = int(Config.EMBED_DIM)
    h = hashlib.md5(text.encode()).digest()
    v = [1.0] + [((h[i % len(h)] / 255.0) - 0.5) * 0.05 for i in range(dim - 1)]
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


class FakeEmbedding:
    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return [fake_vec(t) for t in texts]


MID = "mat_ep01"
QUIZ_JSON = [
    {
        "type": "choice",
        "question": "自注意力涉及哪三个矩阵？",
        "options": {"A": "Q、K、V", "B": "X、Y、Z", "C": "A、B、C", "D": "M、N、P"},
        "correctAnswer": "A",
        "source": {"materialId": MID, "pageNumber": 1, "chunkIndex": 0},
        "knowledgePoint": "自注意力机制",
    },
    {
        "type": "judgment",
        "question": "Transformer 摒弃了循环结构。",
        "correctAnswer": "true",
        "source": {"materialId": MID, "pageNumber": 2, "chunkIndex": 1},
        "knowledgePoint": "Transformer架构",
    },
    {
        "type": "shortAnswer",
        "question": "简述多头注意力的作用。",
        "referenceAnswer": "并行多子空间注意力，拼接后线性变换。",
        "source": {"materialId": MID, "pageNumber": 2, "chunkIndex": 1},
        "knowledgePoint": "多头注意力",
    },
]
REPORT_JSON = {
    "questionSummary": "本周节奏稳定。",
    "coverageSummary": "覆盖良好。",
    "accuracySummary": "正确率提升。",
    "weakPoints": [],
    "nextWeekPlan": ["复习错题", "攻克薄弱点", "学习新资料"],
    "motivation": "继续保持！",
}


def fake_complete(messages, temperature=0.7, max_tokens=None, timeout=None):
    system = messages[0]["content"]
    if system == PROMPT_CHAT_TUTOR:
        return "回答内容"
    if system == PROMPT_QUIZ_MAKER:
        return "```json\n" + json.dumps(QUIZ_JSON, ensure_ascii=False) + "\n```"
    if system == PROMPT_GRADER:
        user = messages[-1]["content"]
        items = json.loads(user.split("请批改以下简答题，严格按 JSON 数组输出：")[1])
        return "```json\n" + json.dumps(
            [
                {
                    "questionId": it["questionId"],
                    "type": "shortAnswer",
                    "score": 0.5,
                    "explanation": "缺少拼接与线性变换。",
                }
                for it in items
            ],
            ensure_ascii=False,
        ) + "\n```"
    if system == PROMPT_REPORT:
        return "```json\n" + json.dumps(REPORT_JSON, ensure_ascii=False) + "\n```"
    return ""


# ---------------- 准备 ----------------
app = create_app()
Session = app.SessionLocal

# 屏蔽真实后台解析线程，只验证路由自身逻辑
materials_route.process_material_async = lambda mid: None
clients.embedding_client.embed = FakeEmbedding().embed
clients.llm_client.complete = fake_complete

with Session() as s:
    s.add(
        Material(
            id=MID,
            title="测试资料",
            file_name="t.md",
            file_type="md",
            file_path="/tmp/t.md",
            file_size=100,
            status="ready",
            chunk_count=3,
            total_pages=2,
        )
    )
    chunks = []
    for i in range(3):
        c = MaterialChunk(
            id=f"{MID}_{i}",
            material_id=MID,
            chunk_index=i,
            page_number=(i % 2) + 1,
            content=f"第{i}段：Transformer 自注意力与多头注意力说明。",
        )
        s.add(c)
        chunks.append(c)
    # 答题数不需要额外造数据：上面第 2 节提交的 3 道题就是硬数据
    s.commit()
    vector_store.add_chunks(MID, "测试资料", "md", chunks, [fake_vec(c.content) for c in chunks])

client = app.test_client()

# ---------------- 1. 资料：重新解析 ----------------
print("[1] 资料 — 重新解析")
r = client.post(f"/api/materials/{MID}/retry")
check("重新解析返回 200", r.status_code == 200)
check("状态重置为 processing", r.get_json()["data"]["status"] == "processing")
with Session() as s:
    n = s.query(MaterialChunk).filter(MaterialChunk.material_id == MID).count()
check("旧分块已清空", n == 0)
r = client.post("/api/materials/not_exist/retry")
check("不存在的资料返回 404", r.status_code == 404)

# 恢复分块供后续用例使用
with Session() as s:
    for i in range(3):
        s.add(
            MaterialChunk(
                id=f"{MID}_{i}",
                material_id=MID,
                chunk_index=i,
                page_number=(i % 2) + 1,
                content=f"第{i}段：Transformer 自注意力与多头注意力说明。",
            )
        )
    s.commit()

# ---------------- 2. 测评：出题 → 提交 ----------------
print("\n[2] 测评 — 出题与提交")
r = client.post("/api/quiz/generate", json={"materialIds": [MID], "questionCount": 3})
quiz_id = r.get_json()["data"]["quizId"]
check("出题成功", r.status_code == 200 and bool(quiz_id))

from models.quiz import QuizQuestion  # noqa: E402

with Session() as s:
    qs = s.query(QuizQuestion).filter(QuizQuestion.quiz_id == quiz_id).all()
answers = [
    {"questionId": q.id, "answer": q.correct_answer if q.type != "shortAnswer" else "并行多子空间"}
    for q in qs
]
r = client.post(f"/api/quiz/{quiz_id}/submit", json={"answers": answers})
submitted = r.get_json()["data"]
check("提交成功", r.status_code == 200 and submitted.get("submissionId"))

# ---------------- 3. 测评：查看结果 ----------------
print("\n[3] 测评 — 查看结果")
r = client.get(f"/api/quiz/{quiz_id}/result")
res = r.get_json()["data"]
check("查看结果返回 200", r.status_code == 200)
check("结果与提交一致（submissionId）", res["submissionId"] == submitted["submissionId"])
check("结果包含每题明细", len(res["results"]) == 3)
check("简答题有参考答案", any("referenceAnswer" in x for x in res["results"]))
check("客观题有正确答案", any("correctAnswer" in x for x in res["results"]))
check("结果含提交时间", bool(res.get("submittedAt")))
r = client.get("/api/quiz/not_exist/result")
check("不存在的测验返回 404", r.status_code == 404)

# ---------------- 4. 测评：历史记录 ----------------
print("\n[4] 测评 — 历史记录")
r = client.get("/api/quiz/history")
hist = r.get_json()["data"]
check("历史记录返回 200", r.status_code == 200)
check("历史含 1 条记录", hist["total"] == 1 and len(hist["list"]) == 1)
item = hist["list"][0]
check("历史含资料名", item["material"] == "测试资料")
check("历史含题数/得分/正确率",
      item["questionCount"] == 3 and isinstance(item["score"], (int, float))
      and isinstance(item["accuracy"], float))
check("历史含用时（秒）", isinstance(item["durationSec"], int))
check("历史含日期", bool(item["date"]))

# ---------------- 5. 进度：总览统计 ----------------
print("\n[5] 进度 — 总览统计")
r = client.get("/api/progress/overview")
ov = r.get_json()["data"]
check("总览返回 200", r.status_code == 200)
check("含资料总数", ov["totalMaterials"] == 1)
check("含分块总数与覆盖", ov["totalChunks"] == 3 and "coverageRate" in ov)
check("含测验次数", ov["totalQuizCount"] == 1)
# 上面第 2 节提交了 3 道题，答题数应当等于 3（硬计数，不折算）
check("含累计答题数（来自 quiz_answers 硬计数）", ov["totalQuestionCount"] == 3)
check("含本周答题数", ov["weekQuestionCount"] == 3)
check("不再返回推算的学习时长", "totalStudyMinutes" not in ov)
check("含连续天数", "currentStreakDays" in ov)
check("含知识点掌握度数组", len(ov["knowledgePoints"]) > 0)
check("知识点含掌握度与等级",
      all("mastery" in k and "level" in k for k in ov["knowledgePoints"]))
check("含资料列表及掌握度", len(ov["materials"]) == 1 and "mastery" in ov["materials"][0])
check("资料含笔记字段", "note" in ov["materials"][0])
check("含薄弱点", "weakPoints" in ov and "weakPointsCount" in ov)
check("含平均正确率", "avgAccuracy" in ov)

# ---------------- 6. 进度：知识点掌握度 ----------------
print("\n[6] 进度 — 知识点掌握度")
r = client.get("/api/progress/knowledge")
kn = r.get_json()["data"]
check("知识点接口返回 200", r.status_code == 200)
check("返回知识点列表", kn["total"] > 0 and len(kn["list"]) > 0)
check("每个知识点有名称/掌握度/等级",
      all(k.get("name") and "mastery" in k and "level" in k for k in kn["list"]))
check("掌握度等级取值合法",
      all(k["level"] in ("熟练", "掌握", "薄弱") for k in kn["list"]))

# ---------------- 7. 薄弱点 ----------------
print("\n[7] 薄弱点")
r = client.get("/api/quiz/weak-points")
wp = r.get_json()["data"]
check("薄弱点接口返回 200", r.status_code == 200)
check("返回错题聚类", wp["totalErrors"] >= 0 and isinstance(wp["weakPoints"], list))
check("薄弱点含知识点与错误次数",
      all("knowledgePoint" in w and "errorCount" in w for w in wp["weakPoints"]))

# ---------------- 8. 周报：生成与下载 ----------------
print("\n[8] 周报 — 生成与下载")
r = client.post("/api/report/generate", json={})
rid = r.get_json()["data"]["reportId"]
check("周报生成成功", r.status_code == 200 and bool(rid))
r = client.get(f"/api/report/{rid}/download")
check("周报下载返回 200", r.status_code == 200)
check("下载类型为 Markdown", "text/markdown" in r.headers["Content-Type"])
check("带附件响应头", "attachment" in r.headers.get("Content-Disposition", ""))
body = r.get_data(as_text=True)
check("Markdown 含标题", body.startswith("# 学习周报"))
check("Markdown 含薄弱知识点章节", "薄弱知识点" in body)
check("Markdown 含下周计划", "下周计划" in body)
r = client.get("/api/report/not_exist/download")
check("不存在的周报下载返回 404", r.status_code == 404)

# 清理
vector_store.delete_material(MID)
try:
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
except OSError:
    pass

print(f"\n结果：通过 {_PASSED} 项，失败 {_FAILED} 项")
sys.exit(1 if _FAILED else 0)
