"""验证「历史对话可保留、可找回、可删除」。

对应前端改动：点「新对话」不再丢弃旧会话，侧栏能列出并点回去。
后端其实早已支持（会话都在 chat_sessions / chat_messages 里），这里验证这条链路真的通：

1. 建会话 A 聊一句 → 再点新对话建会话 B 聊一句
2. 会话列表应同时有 A、B，且按最近活动倒序（B 在前）
3. 回到 A 能完整取回历史消息（这就是用户要的"能找到"）
4. 删除 B 后：列表只剩 A，且 A 的消息不受影响

运行（需先启动后端）：
    .venv/Scripts/python.exe tests/test_chat_sessions.py
"""
import sys
import time

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


def new_session(title, material_ids=None):
    r = requests.post(
        f"{BASE}/api/chat/sessions",
        json={"title": title, "materialIds": material_ids or []},
        timeout=15,
    ).json()
    return r["data"]["sessionId"]


def say(sid, text):
    """用非流式接口发一句（这里只验证存储，不验证流式）"""
    r = requests.post(
        f"{BASE}/api/chat/sessions/{sid}/messages",
        json={"message": text},
        timeout=120,
    ).json()
    if r["code"] != 0:
        raise RuntimeError(r["msg"])
    return r["data"]


def main():
    mats = requests.get(f"{BASE}/api/materials", timeout=15).json()["data"]["list"]
    mats = [m for m in mats if m.get("status") == "ready"]
    mat_id = mats[0]["materialId"] if mats else None
    print(f"资料：{mats[0]['title'] if mats else '（无，用普通对话）'}\n")

    print("【1】会话 A 聊一句")
    a = new_session("会话A-历史验证", [mat_id] if mat_id else [])
    say(a, "用一句话说明这份资料的主题")
    time.sleep(0.3)
    print(f"  A = {a}")

    print("\n【2】点新对话 → 会话 B 再聊一句")
    b = new_session("会话B-历史验证", [mat_id] if mat_id else [])
    say(b, "再说一句它的适用人群")
    time.sleep(0.3)
    print(f"  B = {b}")

    print("\n【3】会话列表应同时保留 A 与 B")
    data = requests.get(f"{BASE}/api/chat/sessions", timeout=15).json()["data"]
    ids = [s["sessionId"] for s in data["list"]]
    check(a in ids, "会话 A 仍在列表中")
    check(b in ids, "会话 B 仍在列表中")
    check(ids.index(b) < ids.index(a), "最近聊过的 B 排在 A 前面（按 updated_at 倒序）")
    sa = next((s for s in data["list"] if s["sessionId"] == a), None)
    sb = next((s for s in data["list"] if s["sessionId"] == b), None)
    check(bool(sa and sa.get("lastMessage")), "A 有最后一条消息预览", (sa or {}).get("lastMessage", "")[:30])
    check(bool(sb and sb.get("lastMessage")), "B 有最后一条消息预览", (sb or {}).get("lastMessage", "")[:30])
    check(bool(sa and sa.get("title")), "A 有标题", (sa or {}).get("title"))

    print("\n【4】回到 A 能完整取回历史")
    msgs = requests.get(
        f"{BASE}/api/chat/sessions/{a}/messages", params={"pageSize": 50}, timeout=15
    ).json()["data"]["list"]
    check(len(msgs) == 2, f"A 有 2 条消息（提问+回答），实际 {len(msgs)}")
    check(any(m["role"] == "user" for m in msgs), "包含用户提问")
    check(any(m["role"] == "assistant" and m["content"] for m in msgs), "包含 AI 回答")
    check(
        all(m["content"] for m in msgs),
        "消息内容都不为空（历史没被清空）",
    )
    # 时间戳必须严格递增：SQLite 的 CURRENT_TIMESTAMP 只到秒，同一轮提问与回答会撞成
    # 同一个时间戳，排序就成了未定义（这里专门守住这个回归）
    roles = [m["role"] for m in msgs]
    check(roles[0] == "user" and roles[1] == "assistant", f"顺序是 提问→回答，实际 {roles}")
    times = [m["createdAt"] for m in msgs]
    check(
        len(set(times)) == len(times),
        "同一轮内消息时间戳互不重复（保证排序稳定）",
        str(times),
    )

    print("\n【5】删除 B")
    requests.delete(f"{BASE}/api/chat/sessions/{b}", timeout=15)
    data2 = requests.get(f"{BASE}/api/chat/sessions", timeout=15).json()["data"]
    ids2 = [s["sessionId"] for s in data2["list"]]
    check(b not in ids2, "B 已从列表移除")
    check(a in ids2, "A 仍在列表")
    msgs2 = requests.get(
        f"{BASE}/api/chat/sessions/{a}/messages", params={"pageSize": 50}, timeout=15
    ).json()["data"]["list"]
    check(len(msgs2) == 2, f"删 B 后 A 的消息仍是 2 条（实际 {len(msgs2)}）")

    print("\n【6】清理本次测试数据")
    requests.delete(f"{BASE}/api/chat/sessions/{a}", timeout=15)
    print("  已删除 A")

    print("\n" + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
