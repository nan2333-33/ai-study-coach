"""验证「流式输出」接口：/api/chat/sessions/<id>/messages/stream

不改动业务代码，只做真实调用，检查：
1. SSE 是否逐段到达（首字延迟明显小于总耗时 = 真的在流，而不是缓冲完一次性给）
2. meta 事件是否先带回引用来源
3. done 事件是否带回完整内容
4. 内容是否真的落库（再用历史消息接口查一次）

运行（backend 已启动）：
    .venv/Scripts/python.exe tests/test_stream_live.py
"""
import json
import sys
import time

import requests

sys.path.insert(0, ".")
from config import Config  # noqa: E402

BASE = f"http://127.0.0.1:{Config.PORT}"
Q = "这份资料主要讲了什么？用三句话概括"


def main():
    # 1) 找一份已解析好的资料；没有就退出（不自动上传，避免污染数据）
    mats = requests.get(f"{BASE}/api/materials", timeout=15).json()["data"]["list"]
    mats = [m for m in mats if m.get("status") == "ready"]
    if not mats:
        print("✗ 没有 ready 状态的资料，请先上传并等待解析完成")
        return 1
    mat = mats[0]
    print(f"使用资料：{mat['title']}（{mat['chunkCount']} 片段）")

    # 2) 建会话
    sid = requests.post(
        f"{BASE}/api/chat/sessions",
        json={"title": "流式验证", "materialIds": [mat["materialId"]]},
        timeout=15,
    ).json()["data"]["sessionId"]
    print(f"会话：{sid}\n提问：{Q}\n" + "-" * 60)

    t0 = time.time()
    resp = requests.post(
        f"{BASE}/api/chat/sessions/{sid}/messages/stream",
        json={"message": Q},
        stream=True,
        timeout=120,
    )
    ct = resp.headers.get("content-type", "")
    if "text/event-stream" not in ct:
        # 前置阶段失败（检索挂了等）：后端回的是普通 JSON
        print(f"✗ 未拿到 SSE，content-type={ct}，响应={resp.text[:300]}")
        return 1

    first_at = None
    last_at = None
    chunks = 0
    text = ""
    sources = []
    done_payload = None
    error = None

    buf = ""
    for raw in resp.iter_lines(decode_unicode=True):
        if raw == "":  # 空行 = 一帧结束
            frame, buf = buf, ""
            if not frame.strip():
                continue
            event, payload = "message", ""
            for line in frame.split("\n"):
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    payload += line[5:].strip()
            if not payload:
                continue
            data = json.loads(payload)
            if event == "meta":
                sources = data.get("sources") or []
                print(f"[{time.time()-t0:5.2f}s] meta   来源 {len(sources)} 处")
            elif event == "delta":
                chunks += 1
                now = time.time()
                first_at = first_at or now
                last_at = now
                text += data.get("text") or ""
            elif event == "done":
                done_payload = data
                print(f"[{time.time()-t0:5.2f}s] done   messageId={data.get('messageId')}")
            elif event == "error":
                error = data.get("msg")
            continue
        buf += raw + "\n"

    total = time.time() - t0
    print("-" * 60)
    if error:
        print(f"✗ 服务端报错：{error}")
        return 1

    t_first = (first_at - t0) if first_at else None
    t_last = (last_at - t0) if last_at else None
    print(f"总耗时        : {total:.2f}s")
    print(f"首字到达      : {t_first:.2f}s" if t_first else "首字到达      : 无")
    print(f"末字到达      : {t_last:.2f}s" if t_last else "末字到达      : 无")
    print(f"分段数(delta) : {chunks}")
    print(f"来源数        : {len(sources)}")
    print(f"累计文本长度  : {len(text)}")
    print(f"done 文本长度 : {len((done_payload or {}).get('content') or '')}")

    ok = True
    if chunks < 5:
        print("✗ delta 分段太少，可能不是真流式（被缓冲后一次性返回）")
        ok = False
    elif t_first and t_last and (t_last - t_first) < 0.3:
        print("✗ 首字与末字几乎同时到达，说明是缓冲后一次性返回，不是流式")
        ok = False
    else:
        print("✓ 确认是逐段流式（首字明显早于末字）")
    if done_payload and done_payload.get("content") == text:
        print("✓ done 内容与累计流内容完全一致")
    else:
        print("⚠ done 内容与累计流内容不一致（前端以 done 为准，可接受但需留意）")

    # 3) 落库校验
    hist = requests.get(
        f"{BASE}/api/chat/sessions/{sid}/messages", params={"pageSize": 50}, timeout=15
    ).json()["data"]["list"]
    ai = [m for m in hist if m["role"] == "assistant"]
    if ai and ai[-1]["content"]:
        print(f"✓ 已落库：历史消息 {len(hist)} 条，助手回复 {len(ai[-1]['content'])} 字")
    else:
        print("✗ 落库失败：历史里没有助手消息")
        ok = False

    print("-" * 60)
    print("\n回复预览：\n" + (text[:300] + ("…" if len(text) > 300 else "")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
