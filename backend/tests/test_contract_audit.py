"""前后台接口契约测试：验证本次审计修复的每一项。

重点覆盖：
1. 判断题选项固定为 {"A":"正确","B":"错误"}，答案统一成 A/B
2. 选择题 options 无论模型返回字符串/数组/对象，都能落成对象
3. 周报 questionCount.changePercent 存在（前端要显示环比）
4. 周报 weakPoints 带 suggestedReview（前端要显示复习建议）
5. /api/progress/trends 返回真实周聚合数据
6. 业务失败时返回非 0 code，前端能据此抛错
7. fileType 归一化（pptx -> ppt）

运行：python tests/test_contract_audit.py
"""
import json
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

TMP = tempfile.mkdtemp(prefix="audit_")
os.environ["DB_URL"] = "sqlite:///" + os.path.join(TMP, "audit.db").replace("\\", "/")
os.environ["CHROMA_DIR"] = os.path.join(TMP, "chroma")

from app import create_app  # noqa: E402
from models import Base  # noqa: E402
from models.material import Material, MaterialChunk  # noqa: E402
from models.learning import LearningSession  # noqa: E402
from services import clients  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("  -> " + str(extra)) if extra else ""))


# ---------- 大模型打桩：不依赖真实 API KEY ----------
QUIZ_RAW = json.dumps(
    [
        {
            "type": "choice",
            "question": "自注意力涉及哪三个矩阵？",
            "options": {"A": "Q、K、V", "B": "X、Y、Z", "C": "a、b、c", "D": "1、2、3"},
            "correctAnswer": "A",
            "knowledgePoint": "自注意力",
            "source": {"materialId": "mat_x", "pageNumber": 3, "chunkIndex": 0},
        },
        {
            "type": "judgment",
            "question": "Transformer 摒弃了循环结构。",
            "correctAnswer": "true",  # 模型常见写法，应被归一成 A
            "knowledgePoint": "Transformer",
            "source": {"materialId": "mat_x", "pageNumber": 1, "chunkIndex": 0},
        },
        {
            "type": "choice",
            "question": "位置编码的作用是？",
            # 故意用数组，验证 _norm_options 兜底
            "options": ["加快训练", "注入顺序信息"],
            "correctAnswer": "B",
            "knowledgePoint": "位置编码",
            "source": {"materialId": "mat_x", "pageNumber": 2, "chunkIndex": 0},
        },
        {
            "type": "shortAnswer",
            "question": "简述多头注意力的作用。",
            "referenceAnswer": "并行多个子空间后拼接线性变换。",
            "knowledgePoint": "多头注意力",
            "source": {"materialId": "mat_x", "pageNumber": 5, "chunkIndex": 0},
        },
    ],
    ensure_ascii=False,
)

STATE = {"n": 0}


def fake_complete(messages, **kw):
    STATE["n"] += 1
    if STATE["n"] == 1:  # 出题
        return "```json\n" + QUIZ_RAW + "\n```"
    if STATE["n"] == 2:  # 改卷
        return json.dumps(
            [{"questionId": "ANY", "score": 0.5, "explanation": "答到一半"}],
            ensure_ascii=False,
        )
    # 周报
    return json.dumps(
        {
            "questionSummary": "本周投入稳定。",
            "nextWeekPlan": ["复习错题", "精读第 3~5 页"],
            "motivation": "继续保持！",
        },
        ensure_ascii=False,
    )


clients.llm_client.complete = fake_complete
clients.embedding_client.embed = lambda texts: [[1.0] + [0.0] * 10 for _ in texts]

app = create_app()
with app.app_context():
    s = app.SessionLocal()
    m = Material(
        id="mat_x", title="Transformer 详解", file_name="t.pdf",
        file_type="pdf", file_path="", file_size=10, status="ready", chunk_count=2,
    )
    s.add(m)
    for i in range(2):
        s.add(MaterialChunk(
            id=f"chk_{i}", material_id="mat_x", chunk_index=i, page_number=i + 1,
            content="自注意力机制通过计算 Q、K、V 三个矩阵得到注意力权重。" * 3,
        ))
    s.add(LearningSession(id="ls_1", session_date=__import__("datetime").date.today(), duration_minutes=60))
    s.commit()
    s.close()

c = app.test_client()

print("\n=== 1. 出题：选项归一 + 判断题固定 A/B ===")
r = c.post("/api/quiz/generate", json={"materialIds": ["mat_x"], "questionCount": 4})
body = r.get_json()
check("generate 返回 code=0", body.get("code") == 0, body)
qs = (body.get("data") or {}).get("questions") or []
check("返回 4 道题", len(qs) == 4, len(qs))

by_type = {q["type"]: q for q in qs}
judge = by_type.get("judgment") or {}
check("判断题 options 固定为 {A:正确,B:错误}", judge.get("options") == {"A": "正确", "B": "错误"}, judge.get("options"))
check("判断题不泄漏正确答案", "correctAnswer" not in judge)

choices = [q for q in qs if q["type"] == "choice"]
check("选择题 options 是对象", all(isinstance(q.get("options"), dict) for q in choices), choices)
check("数组型 options 被转成对象", choices[-1]["options"] == {"A": "加快训练", "B": "注入顺序信息"}, choices[-1].get("options"))

print("\n=== 2. 提交批改：判断题用 A 作答应判对 ===")
quiz_id = body["data"]["quizId"]
answers = []
for q in qs:
    if q["type"] == "judgment":
        answers.append({"questionId": q["questionId"], "answer": "A"})  # 正确答案 true -> A
    elif q["type"] == "choice":
        # 第一道选择题标准答案是 A，第二道是 B，按题意作答
        right = "A" if q["question"].startswith("自注意力") else "B"
        answers.append({"questionId": q["questionId"], "answer": right})
    else:
        answers.append({"questionId": q["questionId"], "answer": "并行多个子空间"})

r = c.post(f"/api/quiz/{quiz_id}/submit", json={"answers": answers, "durationMinutes": 5})
sub = (r.get_json() or {}).get("data") or {}
check("submit 返回 code=0", (r.get_json() or {}).get("code") == 0, r.get_json())
jg = [x for x in sub.get("results", []) if x["type"] == "judgment"]
check("判断题判为正确（A 命中 true）", jg and jg[0]["isCorrect"] is True, jg)
check("结果里 correctAnswer 归一成 A", jg and jg[0]["correctAnswer"] == "A", jg and jg[0].get("correctAnswer"))
check("结果里带 options", jg and jg[0].get("options") == {"A": "正确", "B": "错误"}, jg and jg[0].get("options"))
ch = [x for x in sub.get("results", []) if x["type"] == "choice"]
check("两道选择题都答对", len(ch) == 2 and all(x["isCorrect"] for x in ch), ch)

print("\n=== 3. 查看结果（复用提交结果）===")
r = c.get(f"/api/quiz/{quiz_id}/result")
res = (r.get_json() or {}).get("data") or {}
check("result 接口返回 code=0", (r.get_json() or {}).get("code") == 0)
check("result 与 submit 结构一致", set(res) >= {"submissionId", "quizId", "totalScore", "maxScore", "accuracy", "results"}, list(res))

print("\n=== 4. 历史测评含用时 ===")
r = c.get("/api/quiz/history")
hist = (r.get_json() or {}).get("data") or {}
check("history 有 1 条", hist.get("total") == 1, hist.get("total"))
check("durationSec = 5*60", (hist.get("list") or [{}])[0].get("durationSec") == 300, (hist.get("list") or [{}])[0].get("durationSec"))
check("history 带 material 标题", (hist.get("list") or [{}])[0].get("material") == "Transformer 详解", (hist.get("list") or [{}])[0].get("material"))

print("\n=== 5. 周报：changePercent + suggestedReview ===")
r = c.post("/api/report/generate", json={})
rb = r.get_json() or {}
check("report generate code=0", rb.get("code") == 0, rb)
sec = (rb.get("data") or {}).get("sections") or {}
qc = sec.get("questionCount") or {}
check("questionCount 含 changePercent（前端要用）", "changePercent" in qc, qc)
check("changePercent 是数字不是 None", isinstance(qc.get("changePercent"), (int, float)), qc.get("changePercent"))
check("weakPoints 含 suggestedReview", all("suggestedReview" in w for w in sec.get("weakPoints") or []), sec.get("weakPoints"))
check("nextWeekPlan 是数组", isinstance(sec.get("nextWeekPlan"), list), sec.get("nextWeekPlan"))

rpt_id = (rb.get("data") or {}).get("reportId")
r = c.get(f"/api/report/{rpt_id}")
sec2 = ((r.get_json() or {}).get("data") or {}).get("sections") or {}
check("详情接口 questionCount 也含 changePercent", "changePercent" in (sec2.get("questionCount") or {}), sec2.get("questionCount"))

r = c.get("/api/report/latest")
lat = (r.get_json() or {}).get("data") or {}
check("latest 返回同一份周报", lat.get("reportId") == rpt_id, lat.get("reportId"))
check("latest 的 changePercent 存在", "changePercent" in ((lat.get("sections") or {}).get("questionCount") or {}))

r = c.get("/api/report/history")
hh = (r.get_json() or {}).get("data") or {}
check("history 带 accuracy / weakPointCount", all(
    set(x) >= {"reportId", "weekStart", "weekEnd", "questionCount", "accuracy", "weakPointCount"}
    for x in hh.get("list") or []
), (hh.get("list") or [])[:1])

print("\n=== 6. 进度页 ===")
r = c.get("/api/progress/overview")
ov = (r.get_json() or {}).get("data") or {}
need = ["totalMaterials", "masteredMaterials", "totalQuestionCount", "avgAccuracy",
        "weakPointsCount", "knowledgePoints", "materials", "weakPoints", "totalQuizCount"]
check("overview 字段齐全（前端 5 张卡 + 列表）", all(k in ov for k in need), [k for k in need if k not in ov])
check("weakPoints 带 suggestedReview", all("suggestedReview" in w for w in ov.get("weakPoints") or []), ov.get("weakPoints"))
check("materials[i].note 是对象", all(isinstance(m.get("note"), dict) for m in ov.get("materials") or []), ov.get("materials"))

r = c.get("/api/progress/trends")
tr = (r.get_json() or {}).get("data") or {}
pts = tr.get("points") or []
check("trends 返回 8 个点（原来为空数组）", len(pts) == 8, len(pts))
check("trends 点含 label / value", all(set(p) >= {"label", "value"} for p in pts), pts[:1])
check("trends value 是数字", all(isinstance(p["value"], (int, float)) for p in pts))

print("\n=== 7. 失败时返回非 0 code（前端据此抛错）===")
r = c.post("/api/quiz/generate", json={"materialIds": [], "questionCount": 4})
check("materialIds 为空 -> code!=0", (r.get_json() or {}).get("code") != 0, r.get_json())
check("失败时带 msg", bool((r.get_json() or {}).get("msg")))
r = c.get("/api/materials/not_exist")
check("资料不存在 -> 404", r.status_code == 404, r.status_code)
r = c.post("/api/chat/sessions/xxx/messages", json={"message": ""})
check("message 为空 -> code!=0", (r.get_json() or {}).get("code") != 0, r.get_json())

print("\n=== 8. fileType 归一化 ===")
r = c.get("/api/materials")
fts = [m["fileType"] for m in ((r.get_json() or {}).get("data") or {}).get("list") or []]
check("fileType 为 pdf", fts == ["pdf"], fts)

# 直接验证归一化函数
from routes.materials import _norm_type  # noqa: E402
check("pptx -> ppt", _norm_type("pptx") == "ppt")
check("docx -> doc", _norm_type("docx") == "doc")
check("markdown -> md", _norm_type("markdown") == "md")

print("\n=== 9. 前端不存在的接口已清理 ===")
api_src = open(os.path.join(BACKEND, "..", "js", "api.js"), encoding="utf-8").read()
check("api.js 不再声明 resolveMaterial", "resolveMaterial" not in api_src)
check("api.js 请求失败会抛错", "r.code !== 0" in api_src)
check("api.js 上传失败会抛错", "上传失败" in api_src)
app_src = open(os.path.join(BACKEND, "..", "js", "app.js"), encoding="utf-8").read()
check("app.js 不再硬编码 mat_001", "mat_001" not in app_src)
check("app.js 有选项归一化", "function normalizeOptions" in app_src)
check("app.js 判断题固定 A/B", 'A: "正确"' in app_src and 'B: "错误"' in app_src)

print("\n" + "=" * 46)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败明细：")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("全部通过")
