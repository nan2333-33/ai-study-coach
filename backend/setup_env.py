"""配置向导：把大模型 / 向量模型的密钥写进 .env。

用法：
    python setup_env.py                          交互式填写（推荐首次使用）
    python setup_env.py --check                  只检查当前配置是否完整，不修改文件
    python setup_env.py --set LLM_API_KEY=sk-xxx --set EMB_API_KEY=sk-xxx
                                                 命令行直接写入（只改指定项，其余保留）

说明：
    1. 密钥只在你自己的终端里输入，不会被写进任何日志或对话记录。
    2. 每一项的当前值会打码显示，直接回车可保留原值。
    3. 改完必须重启后端才生效。
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
EXAMPLE_PATH = os.path.join(BASE_DIR, ".env.example")

# (键名, 提示语, 默认值, 是否必填)
ITEMS = [
    ("LLM_BASE_URL", "大模型接口地址", "https://api.deepseek.com/v1", True),
    ("LLM_API_KEY", "DeepSeek API Key（sk- 开头）", None, True),
    ("LLM_MODEL", "大模型名称", "deepseek-chat", True),
    ("EMBED_BASE_URL", "向量模型接口地址（阿里云百炼兼容模式）",
     "https://dashscope.aliyuncs.com/compatible-mode/v1", True),
    ("EMB_API_KEY", "阿里云百炼 API Key（sk- 开头，注意是 EMB_ 不是 EMBED_）", None, True),
    ("EMBED_MODEL", "向量模型名称", "text-embedding-v4", True),
    ("EMBED_DIM", "向量维度（百炼 text-embedding-v4 填 1024）", "1024", True),
]

PLACEHOLDER_HINTS = ("your", "your-embed", "changeme", "xxx", "xxx")


def mask(v):
    """打码显示，避免密钥回显到屏幕或日志。"""
    if not v:
        return "(空)"
    s = str(v)
    if len(s) <= 12:
        return s[:3] + "***"
    return s[:7] + "***" + s[-4:]


def is_placeholder(v):
    v = (v or "").strip().lower()
    return (not v) or any(h in v for h in PLACEHOLDER_HINTS)


def read_env(path):
    """读 .env 成 dict（不依赖 python-dotenv，避免脚本在装依赖前跑不了）。"""
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def write_env(path, updates):
    """按行原地更新 .env：只改值，保留原有注释与顺序；缺失的键追加到末尾。"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    else:
        lines = []

    hit = set()
    out = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                hit.add(k)
                continue
        out.append(line)

    todo = [k for k, _, _, _ in ITEMS if k in updates and k not in hit]
    if todo:
        out.append("")
        out.append("# ===== 由 setup_env.py 追加 =====")
        for k in todo:
            out.append(f"{k}={updates[k]}")

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")


def check_only():
    data = read_env(ENV_PATH)
    print(f"配置文件：{ENV_PATH}")
    print(f"是否存在：{'是' if os.path.exists(ENV_PATH) else '否（请先运行 python setup_env.py）'}\n")
    bad = []
    for key, desc, _default, required in ITEMS:
        v = data.get(key, "")
        ok = not is_placeholder(v)
        flag = "OK  " if ok else "缺失"
        print(f"  [{flag}] {key:16} {mask(v):24} {desc}")
        if required and not ok:
            bad.append(key)
    print()
    if bad:
        print(f"配置不完整，还需填写：{', '.join(bad)}")
        print("运行 python setup_env.py 开始填写")
        return 1
    print("配置完整。若后端已在运行，请重启后端使配置生效。")
    return 0


def interactive():
    if not os.path.exists(ENV_PATH):
        if os.path.exists(EXAMPLE_PATH):
            with open(EXAMPLE_PATH, "r", encoding="utf-8-sig") as f:
                content = f.read()
            with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            print(f"已从模板创建 {ENV_PATH}\n")
        else:
            print("找不到 .env.example，无法初始化")
            return 1

    cur = read_env(ENV_PATH)

    print("=" * 60)
    print("配置向导：填写大模型与向量模型的密钥")
    print("=" * 60)
    print("· 直接回车 = 保留当前值（括号内为当前值，已打码）")
    print("· 输入内容会显示在屏幕上，但不会被保存到任何日志")
    print("· 随时按 Ctrl+C 退出，已填的内容不会写入\n")

    updates = {}
    for key, desc, default, required in ITEMS:
        now = cur.get(key, "")
        tip = f"{desc}\n  当前值: {mask(now)}"
        if is_placeholder(now) and default:
            tip += f"  （建议: {default}）"
        prompt = tip + "\n  新值 > "
        try:
            val = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n已取消，未写入任何内容。")
            return 1

        if not val:
            if is_placeholder(now) and default:
                val = default
            else:
                val = now

        # 轻度校验：Key 类字段看着像 sk- 开头
        if key.endswith("API_KEY") and val and not val.startswith("sk-"):
            print("  ⚠ 这个值不像 API Key（一般 sk- 开头），仍会写入，请自行确认。")
        updates[key] = val
        print()

    write_env(ENV_PATH, updates)

    print("=" * 60)
    print(f"已写入 {ENV_PATH}\n")
    for key, _desc, _d, _r in ITEMS:
        print(f"  {key:16} {mask(updates.get(key, ''))}")
    print("\n下一步：")
    print("  1) 重启后端（改 .env 不会热重载）")
    print("  2) python setup_env.py --check  可随时复查")
    return 0


def parse_set_args(argv):
    """解析 --set KEY=VALUE（也兼容 --set=KEY=VALUE）。"""
    pairs = {}
    for i, a in enumerate(argv):
        if a == "--set" and i + 1 < len(argv):
            raw = argv[i + 1]
        elif a.startswith("--set="):
            raw = a[len("--set="):]
        else:
            continue
        if "=" not in raw:
            print(f"  ✗ --set 格式不对：{raw}（应为 KEY=VALUE）")
            return None
        k, v = raw.split("=", 1)
        pairs[k.strip()] = v.strip()
    return pairs


def apply_set(pairs):
    """命令行直接写入指定项，其余保持不变。"""
    if not os.path.exists(ENV_PATH):
        if os.path.exists(EXAMPLE_PATH):
            with open(EXAMPLE_PATH, "r", encoding="utf-8-sig") as f:
                content = f.read()
            with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            print(f"已从模板创建 {ENV_PATH}")
        else:
            print("找不到 .env.example，无法初始化")
            return 1

    known = {k for k, _, _, _ in ITEMS}
    unknown = [k for k in pairs if k not in known]
    if unknown:
        print(f"  ✗ 未知配置项：{', '.join(unknown)}")
        print(f"    可用：{', '.join(sorted(known))}")
        return 1

    write_env(ENV_PATH, pairs)

    print(f"已写入 {ENV_PATH}\n")
    for k, v in pairs.items():
        print(f"  {k:16} {mask(v)}")
    print("\n剩余未配置项可用 python setup_env.py --check 查看。")
    print("改完记得重启后端才会生效。")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check_only())
    pairs = parse_set_args(sys.argv[1:])
    if pairs is None:
        sys.exit(1)
    if pairs:
        sys.exit(apply_set(pairs))
    sys.exit(interactive())
