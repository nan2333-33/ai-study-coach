"""LLM 返回的 JSON 清洗与解析。

AI 有时会在 JSON 外面包一层 ```json ... ``` 围栏，或前后带说明文字。
这里统一去掉围栏、截取首尾 JSON 片段，保证 json.loads 稳定。
"""
import json
import re


def strip_code_fence(text):
    """去掉 ```json ... ``` 或 ``` ... ``` 围栏。"""
    if not text:
        return text
    t = text.strip()
    # 匹配整段被围栏包裹的情况（允许首行带或不带 json 标记）
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return t


def extract_json(text):
    """从模型输出中尽量解析出 JSON（dict 或 list）。

    处理两种常见情况：
    1. 输出整体就是 JSON（可能带围栏）
    2. 输出前后夹带解释文字，JSON 在中间
    """
    t = strip_code_fence(text or "")

    # 1) 直接解析
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # 2) 截取第一个 { 或 [ 到最后一个 } 或 ]
    first_brace = t.find("{")
    first_bracket = t.find("[")
    candidates = [i for i in (first_brace, first_bracket) if i != -1]
    if not candidates:
        raise ValueError("模型输出中未找到 JSON 内容")
    start = min(candidates)
    end_ch = "}" if t[start] == "{" else "]"
    end = t.rfind(end_ch)
    if end == -1 or end < start:
        raise ValueError("模型输出的 JSON 结构不完整")

    snippet = t[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as e:
        raise ValueError(f"解析模型 JSON 失败: {e}")


def extract_json_list(text):
    """强制解析为 list（出题 / 批改返回数组时更顺手）。"""
    data = extract_json(text)
    if not isinstance(data, list):
        raise ValueError("期望模型返回 JSON 数组，实际不是")
    return data
