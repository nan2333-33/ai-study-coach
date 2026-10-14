"""验证测评三处修复：
  1. 批改结果的顺序 == 出卷顺序（原来因为时间戳只到秒，顺序被打乱）
  2. 选择题/判断题也有 AI 解析（原来 explanation 恒为 None）
  3. 历史测评能回看：列表带 quizId，且能按提交记录取回题干与解析

运行（需先启动后端）：
    .venv/Scripts/python.exe tests/test_quiz_live.py
"""
import sys

import requests

sys.path.insert(0, ".")
from config import Config  # noqa: E402

BASE = f"http://127.0.0.1:{Config.PORT}"
ok = True


def check(cond, label, extra=""):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + label + (f"  {extra}" if extra else ""))
    if not cond:
        ok = False


def main():
    mats = requests.get(f"{BASE}/api/materials", timeout=15).json()["data"]["list"]
    mats = [m for m in mats if m.get("status") == "ready"]
    if not mats:
        print("✗ 没有 ready 状态的资料")
        return 1
    mat = mats[0]
    print(f"出题资料：{mat['title']}\n")

    print("【1】生成一套 4 题的测验")
    r = requests.post(
        f"{BASE}/api/quiz/generate",
        json={"materialIds": [mat["materialId"]], "questionCount": 4},
        timeout=180,
    ).json()
    if r["code"] != 0:
        print("✗ 出题失败：", r["msg"])
        return 1
    quiz = r["data"]
    qs = quiz["questions"]
    print(f"  quizId={quiz['quizId']}，共 {len(qs)} 题")
    for i, q in enumerate(qs):
        print(f"    {i + 1}. [{q['type']}] {q['question'][:34]}")

    print("\n【2】提交（客观题全选第一个选项，简答题写一句话）")
    answers = []
    for q in qs:
        if q["type"] == "shortAnswer":
            answers.append({"questionId": q["questionId"], "answer": "略知一二，但说不全。"})
        else:
            opts = q.get("options") or {}
            answers.append(
                {"questionId": q["questionId"], "answer": sorted(opts.keys())[0]}
            )
    r2 = requests.post(
        f"{BASE}/api/quiz/{quiz['quizId']}/submit",
        json={"answers": answers, "durationMinutes": 2},
        timeout=180,
    ).json()
    if r2["code"] != 0:
        print("✗ 批改失败：", r2["msg"])
        return 1
    res = r2["data"]
    print(f"  得分 {res['totalScore']}/{res['maxScore']}，正确率 {res['accuracy']}")

    print("\n【3】结果顺序必须与出卷顺序一致")
    got_ids = [x["questionId"] for x in res["results"]]
    want_ids = [q["questionId"] for q in qs]
    check(got_ids == want_ids, "结果顺序 == 出卷顺序")
    if got_ids != want_ids:
        print("    出卷：", want_ids)
        print("    结果：", got_ids)

    print("\n【4】每条结果都要带题干（历史回看靠它）")
    check(
        all(x.get("question") for x in res["results"]),
        "所有结果都有题干",
        str([bool(x.get("question")) for x in res["results"]]),
    )

    print("\n【5】选择题 / 判断题必须有 AI 解析")
    for x in res["results"]:
        if x["type"] in ("choice", "judgment"):
            exp = (x.get("explanation") or "").strip()
            check(
                len(exp) > 0,
                f"{x['type']} 有解析（得分 {x['score']}）",
                exp[:40] + ("…" if len(exp) > 40 else ""),
            )
    obj = [x for x in res["results"] if x["type"] in ("choice", "judgment")]
    check(len(obj) > 0, f"本套含客观题 {len(obj)} 道（否则这项测不到）")

    print("\n【6】历史列表带 quizId，且能回看")
    hist = requests.get(f"{BASE}/api/quiz/history", params={"pageSize": 5}, timeout=15).json()["data"]
    row = next((x for x in hist["list"] if x["recordId"] == res["submissionId"]), None)
    check(row is not None, "本次提交出现在历史列表")
    check(bool(row and row.get("quizId")), "历史条目带 quizId", (row or {}).get("quizId", ""))

    sub = requests.get(
        f"{BASE}/api/quiz/submissions/{res['submissionId']}", timeout=15
    ).json()
    check(sub["code"] == 0, "按提交记录可取回结果")
    if sub["code"] == 0:
        d = sub["data"]
        check(len(d["results"]) == len(qs), f"回看结果条数 {len(d['results'])} == {len(qs)}")
        check(all(x.get("question") for x in d["results"]), "回看结果都带题干")
        check(
            [x["questionId"] for x in d["results"]] == want_ids,
            "回看顺序也与出卷一致",
        )

    print("\n" + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
