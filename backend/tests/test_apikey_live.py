"""真实连通性自检：验证两个 API Key 是否真的可用（生产环境，会消耗极少量额度）。

用法：
    python tests/test_apikey_live.py

只输出成功/失败与耗时，不打印任何密钥内容。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests
except ImportError:
    print("缺少 requests，请先 pip install -r requirements.txt")
    sys.exit(1)

from config import Config

LLM_BASE_URL = Config.LLM_BASE_URL
LLM_API_KEY = Config.LLM_API_KEY
LLM_MODEL = Config.LLM_MODEL
EMBED_BASE_URL = Config.EMBED_BASE_URL
EMB_API_KEY = Config.EMBED_API_KEY      # 注意：Python 侧叫 EMBED_API_KEY，.env 里写 EMB_API_KEY
EMBED_MODEL = Config.EMBED_MODEL
EMBED_DIM = Config.EMBED_DIM


def mask(v):
    if not v:
        return "(空)"
    return v[:7] + "***" + v[-4:] if len(v) > 12 else v[:3] + "***"


def test_llm():
    print("-" * 56)
    print("1) 大模型 DeepSeek —— 对话能力（聊天/出题/批改/周报都靠它）")
    print(f"   地址: {LLM_BASE_URL}")
    print(f"   模型: {LLM_MODEL}")
    print(f"   Key : {mask(LLM_API_KEY)}")
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    t0 = time.time()
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {LLM_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": LLM_MODEL,
                  "messages": [{"role": "user", "content": "只回复两个字：正常"}],
                  "max_tokens": 16, "temperature": 0},
            timeout=60,
        )
    except Exception as e:
        print(f"   ✗ 请求失败: {type(e).__name__}: {e}")
        return False
    cost = time.time() - t0
    if r.status_code != 200:
        print(f"   ✗ HTTP {r.status_code}: {r.text[:300]}")
        return False
    try:
        content = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        print(f"   ✗ 返回格式异常: {r.text[:300]}")
        return False
    print(f"   ✓ 调用成功，耗时 {cost:.1f}s，AI 回复: {content}")
    return True


def test_embed():
    print("-" * 56)
    print("2) 向量模型 阿里云百炼 —— 资料解析必须用它")
    print(f"   地址: {EMBED_BASE_URL}")
    print(f"   模型: {EMBED_MODEL}   期望维度: {EMBED_DIM}")
    print(f"   Key : {mask(EMB_API_KEY)}")
    url = EMBED_BASE_URL.rstrip("/") + "/embeddings"
    t0 = time.time()
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {EMB_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": EMBED_MODEL, "input": ["连通性测试"]},
            timeout=60,
        )
    except Exception as e:
        print(f"   ✗ 请求失败: {type(e).__name__}: {e}")
        return False
    cost = time.time() - t0
    if r.status_code != 200:
        print(f"   ✗ HTTP {r.status_code}: {r.text[:300]}")
        return False
    try:
        vec = r.json()["data"][0]["embedding"]
    except Exception:
        print(f"   ✗ 返回格式异常: {r.text[:300]}")
        return False
    dim = len(vec)
    flag = "✓" if dim == int(EMBED_DIM) else "✗"
    print(f"   {flag} 调用成功，耗时 {cost:.1f}s，实际维度 {dim}（配置写的 {EMBED_DIM}）")
    if dim != int(EMBED_DIM):
        print(f"   ⚠ 维度不一致！请把 .env 的 EMBED_DIM 改成 {dim}，")
        print("     然后删除 backend/data/chroma/ 目录重建向量库，否则资料会解析失败。")
        return False
    return True


if __name__ == "__main__":
    print("=" * 56)
    print("API Key 真实连通性自检")
    print("=" * 56)
    ok1 = test_llm()
    ok2 = test_embed()
    print("=" * 56)
    if ok1 and ok2:
        print("两项全部通过，可以启动后端跑完整流程了。")
        sys.exit(0)
    print("存在问题，按上面的提示处理后再测一次：")
    if not ok1:
        print("  - 大模型 Key 不可用")
    if not ok2:
        print("  - 向量模型 Key 不可用")
    sys.exit(1)
