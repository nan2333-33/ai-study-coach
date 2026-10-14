"""DeepSeek 接入验证：聊天 RAG / 出题 / 批改 / 周报 + 重试 + JSON 围栏剥离。

用 FakeLLM / FakeEmbedding 替代真实模型，不依赖任何 API Key。
运行：python tests/test_llm_integration.py
"""
import io
import json
import os
import sys
import tempfile
from unittest.mock import patch

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

_TMP_DB = os.path.join(tempfile.gettempdir(), "ailms_llm_test.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DB_URL"] = "sqlite:///" + _TMP_DB

import requests  # noqa: E402

from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from models.material import Material, MaterialChunk  # noqa: E402
from models.knowledge import ErrorBook  # noqa: E402
from models.quiz import QuizQuestion  # noqa: E402
from services import clients  # noqa: E402
from services.prompts import (  # noqa: E402
    PROMPT_CHAT_TUTOR,
    PROMPT_QUIZ_MAKER,
    PROMPT_GRADER,
    PROMPT_REPORT,
)
from services.vector_store import vector_store  # noqa: E402
from utils.json_util import extract_json, extract_json_list  # noqa: E402

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
    """假向量：带一个主导常量分量，保证任意两段文本的余弦相似度足够高，
    从而通过 RETRIEVE_MIN_SCORE 阈值（纯哈希向量会导致相似度接近 0 被过滤）。"""
    import hashlib
    import math

    from config import Config

    dim = int(Config.EMBED_DIM)  # 维度要跟 collection 一致，写死 16 会被 Chroma 拒
    h = hashlib.md5(text.encode()).digest()
    v = [1.0] + [((h[i % len(h)] / 255.0) - 0.5) * 0.05 for i in range(dim - 1)]
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


class FakeEmbedding:
    dim = 16

    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return [fake_vec(t) for t in texts]


QUIZ_JSON = [
    {
        "type": "choice",
        "question": "自注意力机制涉及哪三个矩阵？",
        "options": {
            "A": "Query、Key、Value",
            "B": "Input、Hidden、Output",
            "C": "Embedding、Position、Context",
            "D": "Forward、Backward、Update",
        },
        "correctAnswer": "A",
        "source": {"materialId": "MATID", "pageNumber": 1, "chunkIndex": 0},
        "knowledgePoint": "自注意力机制",
    },
    {
        "type": "choice",
        "question": "Transformer 编码器层包含什么？",
        "options": {
            "A": "卷积层",
            "B": "多头注意力与前馈网络",
            "C": "循环层",
            "D": "池化层",
        },
        "correctAnswer": "B",
        "source": {"materialId": "MATID", "pageNumber": 2, "chunkIndex": 1},
        "knowledgePoint": "Transformer架构",
    },
    {
        "type": "judgment",
        "question": "Transformer 完全摒弃了循环神经网络结构。",
        "correctAnswer": "true",
        "source": {"materialId": "MATID", "pageNumber": 1, "chunkIndex": 0},
        "knowledgePoint": "Transformer架构",
    },
    {
        "type": "shortAnswer",
        "question": "简述多头注意力的作用。",
        "referenceAnswer": "并行多次注意力，不同子空间投影，拼接后线性变换。",
        "source": {"materialId": "MATID", "pageNumber": 2, "chunkIndex": 1},
        "knowledgePoint": "多头注意力",
    },
]

REPORT_JSON = {
    "questionSummary": "本周做题量稳定。",
    "coverageSummary": "资料覆盖良好。",
    "accuracySummary": "正确率较上周有提升。",
    "weakPoints": [],
    "nextWeekPlan": ["复习错题", "攻克薄弱点", "学习新资料"],
    "motivation": "保持节奏，下周继续！",
}


def _fenced(payload):
    """故意包一层 ```json 围栏，验证自动剥离。"""
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def make_fake_llm():
    calls = []

    def fake_complete(messages, temperature=0.7, max_tokens=None, timeout=None):
        system = messages[0]["content"]
        calls.append(system)
        if system == PROMPT_CHAT_TUTOR:
            return "Transformer 的核心是自注意力机制。来源：《测试资料》第 1 页"
        if system == PROMPT_QUIZ_MAKER:
            raw = json.dumps(QUIZ_JSON, ensure_ascii=False).replace("MATID", MID)
            return "```json\n" + raw + "\n```"
        if system == PROMPT_GRADER:
            user = messages[-1]["content"]
            items = json.loads(user.split("请批改以下简答题，严格按 JSON 数组输出：")[1])
            graded = [
                {
                    "questionId": it["questionId"],
                    "type": "shortAnswer",
                    "score": 0.5,
                    "explanation": "缺少拼接与线性变换说明。",
                }
                for it in items
            ]
            return _fenced(graded)
        if system == PROMPT_REPORT:
            return _fenced(REPORT_JSON)
        return "未知任务"

    return fake_complete, calls


# ---------------- 1. JSON 围栏剥离 ----------------
print("[1] JSON 围栏剥离")
check("去掉 ```json 围栏", extract_json_list(_fenced([{"a": 1}])) == [{"a": 1}])
check("去掉无语言标记围栏", extract_json("```\n{\"a\": 2}\n```") == {"a": 2})
check(
    "前后夹带说明文字也能解析",
    extract_json_list("好的，结果如下：\n" + _fenced([{"a": 3}]) + "\n以上是结果") == [{"a": 3}],
)
check("无围栏纯 JSON 直接解析", extract_json('{"a": 4}') == {"a": 4})

# ---------------- 2. 失败自动重试最多 3 次 ----------------
print("\n[2] 大模型调用失败自动重试（最多 3 次）")


class _Resp:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


llm = clients.LLMClient()
llm.base_url = "https://api.deepseek.com/v1"
llm.api_key = "sk-test-key"
llm.model = "deepseek-chat"
llm.max_retries = 3

with patch.object(requests, "post") as mock_post:
    mock_post.side_effect = [
        requests.exceptions.ConnectionError("网络中断"),
        requests.exceptions.Timeout("超时"),
        requests.exceptions.ConnectionError("网络中断"),
        _Resp(),
    ]
    out = llm.complete([{"role": "user", "content": "hi"}])
check("连续失败 3 次后第 4 次成功，返回结果", out == "ok")
check("共尝试 4 次（1 次调用 + 3 次重试）", mock_post.call_count == 4)

with patch.object(requests, "post") as mock_post2:
    mock_post2.side_effect = requests.exceptions.ConnectionError("一直失败")
    err = None
    try:
        llm.complete([{"role": "user", "content": "hi"}])
    except Exception as e:
        err = e
check("一直失败时抛出异常", err is not None)
check("一直失败时同样只尝试 4 次", mock_post2.call_count == 4)

# ---------------- 3. 业务链路 ----------------
print("\n[3] 四个能力链路（聊天 / 出题 / 批改 / 周报）")

app = create_app()
Session = app.SessionLocal

# 准备一份已处理完成的资料（含分块 + 向量）
MID = "mat_test01"
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
            content=f"第{i}段：Transformer 的核心是自注意力机制，涉及 Query、Key、Value 三个矩阵。",
            token_count=50,
        )
        s.add(c)
        chunks.append(c)
    s.commit()
    vector_store.add_chunks(
        MID, "测试资料", "md", chunks, [fake_vec(c.content) for c in chunks]
    )

# 替换掉真实模型客户端（模块内引用的是同一个单例对象）
clients.embedding_client.embed = FakeEmbedding().embed
fake_complete, llm_calls = make_fake_llm()
clients.llm_client.complete = fake_complete

client = app.test_client()

# 3.1 聊天 RAG
r = client.post("/api/chat/sessions", json={"materialIds": [MID], "title": "测试会话"})
session_id = r.get_json()["data"]["sessionId"]
check("创建会话成功", r.status_code == 200 and bool(session_id))

r = client.post(
    f"/api/chat/sessions/{session_id}/messages",
    json={"message": "Transformer 的核心是什么？"},
)
data = r.get_json()["data"]
check("聊天返回 AI 回答", r.status_code == 200 and "自注意力" in data["content"])
check("聊天返回来源引用（C-02）", len(data["sources"]) > 0)
check("来源含资料标题与页码", data["sources"][0].get("title") == "测试资料")
check("聊天使用了提示词 A", PROMPT_CHAT_TUTOR in llm_calls)

# 3.2 出题
r = client.post(
    "/api/quiz/generate", json={"materialIds": [MID], "questionCount": 4}
)
quiz = r.get_json()["data"]
check("出题成功", r.status_code == 200 and quiz.get("quizId"))
check("生成 4 道题", len(quiz["questions"]) == 4)
check("出题使用了提示词 B", PROMPT_QUIZ_MAKER in llm_calls)
types = [q["type"] for q in quiz["questions"]]
check("题型配比：2 选择 / 1 判断 / 1 简答", sorted(types) == ["choice", "choice", "judgment", "shortAnswer"])
check("返回题目不包含正确答案", all("correctAnswer" not in q for q in quiz["questions"]))
check("返回题目包含来源", all(q.get("source") for q in quiz["questions"]))

with Session() as s:
    qs = s.query(QuizQuestion).filter(QuizQuestion.quiz_id == quiz["quizId"]).all()
check("题目已落库", len(qs) == 4)

# 3.3 批改
answers = []
for q in qs:
    if q.type == "choice":
        answers.append({"questionId": q.id, "answer": q.correct_answer})  # 答对
    elif q.type == "judgment":
        answers.append({"questionId": q.id, "answer": "false"})  # 答错
    else:
        answers.append({"questionId": q.id, "answer": "多头注意力可以并行关注不同位置"})

r = client.post(f"/api/quiz/{quiz['quizId']}/submit", json={"answers": answers})
sub = r.get_json()["data"]
check("批改成功", r.status_code == 200 and sub.get("submissionId"))
res = {x["type"]: x for x in sub["results"]}
check("选择题答对得 1 分", any(x["type"] == "choice" and x["score"] == 1 for x in sub["results"]))
check("判断题答错得 0 分", res["judgment"]["score"] == 0 and res["judgment"]["isCorrect"] is False)
check("简答题由改卷官打分 0.5", res["shortAnswer"]["score"] == 0.5)
check("简答题返回评语", bool(res["shortAnswer"].get("explanation")))
check("批改使用了提示词 C", PROMPT_GRADER in llm_calls)
check("总分 = 2×1 + 0 + 0.5 = 2.5", sub["totalScore"] == 2.5)
check("正确率 = 2.5/4", sub["accuracy"] == 0.625)

with Session() as s:
    errs = s.query(ErrorBook).all()
check("错题本收录未满分题目（2 条）", len(errs) == 2)

# 3.4 周报
r = client.post("/api/report/generate", json={})
rep = r.get_json()["data"]
check("周报生成成功", r.status_code == 200 and rep.get("reportId"))
check("周报使用了提示词 D", PROMPT_REPORT in llm_calls)
sec = rep["sections"]
check("周报含做题量（答题数，非推算时长）", sec["questionCount"]["thisWeek"] is not None)
check("周报含薄弱点", "weakPoints" in sec)
check("周报含下周计划（AI 生成）", len(sec["nextWeekPlan"]) == 3)
check("周报含激励语（AI 生成）", bool(sec["motivation"]))
check("周报正确率取自真实数据", sec["accuracyTrend"]["thisWeek"] == 0.625)

r = client.get("/api/report/latest")
check("可读取最新周报", r.status_code == 200 and r.get_json()["data"] is not None)

# 清理（Windows 下数据库文件可能仍被占用，忽略清理失败）
vector_store.delete_material(MID)
try:
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
except OSError:
    pass

print(f"\n结果：通过 {_PASSED} 项，失败 {_FAILED} 项")
sys.exit(1 if _FAILED else 0)
