"""大模型与向量模型客户端。

两个模型完全独立配置（见 config.py / .env）：
- LLMClient       : 对话（支持流式）/ 出题 / 批改（待后续模块实现）
- EmbeddingClient : 文本向量化，对接阿里云百炼 OpenAI 兼容模式

阿里云百炼 embedding 兼容模式端点示例：
    EMBED_BASE_URL = https://dashscope.aliyuncs.com/compatible-mode/v1
    EMBED_MODEL    = text-embedding-v4
调用 /embeddings，入参含 model / input / dimensions（可选），返回 data[i].embedding。
"""
import json
import os
import time

import requests

from config import Config


class LLMClient:
    """大模型客户端（OpenAI Chat Completions 兼容格式）。

    默认对接 DeepSeek：
        LLM_BASE_URL = https://api.deepseek.com/v1
        LLM_MODEL    = deepseek-chat
    失败（网络异常 / 超时 / 非 200）自动重试，最多重试 LLM_MAX_RETRIES 次（默认 3）。
    """

    def __init__(self):
        self.base_url = (Config.LLM_BASE_URL or "").rstrip("/")
        self.api_key = Config.LLM_API_KEY
        self.model = Config.LLM_MODEL
        self.max_retries = Config.LLM_MAX_RETRIES
        self.timeout = Config.LLM_TIMEOUT

    def _chat_endpoint(self):
        if not self.base_url or "your-llm" in self.base_url:
            raise ValueError(
                "LLM_BASE_URL 未正确配置（请在 .env 填写大模型地址，"
                "DeepSeek 为 https://api.deepseek.com/v1）"
            )
        if not self.api_key or "your" in self.api_key:
            raise ValueError("LLM_API_KEY 未正确配置（请在 .env 填写 DeepSeek 的 API Key）")
        return self.base_url + "/chat/completions"

    def complete(self, messages, temperature=0.7, max_tokens=None, timeout=None):
        """调用大模型，返回回复文本（str）。

        messages 为 [{"role": "system"/"user"/"assistant", "content": ...}]
        失败（网络异常 / 超时 / 非 200）自动重试最多 max_retries 次，退避后再试。
        """
        endpoint = self._chat_endpoint()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        last_err = None
        # 首次调用 + 最多 max_retries 次重试（共 1 + max_retries 次尝试）
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout or self.timeout,
                )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"大模型调用失败 HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:  # 网络异常 / 超时 / 非 200，都计入重试
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))  # 1s / 2s / 4s 退避
                    continue
                raise RuntimeError(
                    f"大模型调用失败（已重试 {self.max_retries} 次）：{last_err}"
                ) from last_err
        raise RuntimeError(f"大模型调用失败：{last_err}")

    def complete_stream(self, messages, temperature=0.7, max_tokens=None, timeout=None):
        """流式调用大模型，逐段 yield 文本增量（用于打字机效果）。

        走 OpenAI 兼容的 SSE：请求体加 "stream": true，响应逐行返回
            data: {"choices":[{"delta":{"content":"你"}}]}
            ...
            data: [DONE]
        只 yield content 增量；空 delta（如首包的 role 帧）直接跳过。

        注意：流式**不做重试**——连接一旦建立并已吐出部分内容，重放会重复。
        若需要兜底，由调用方在未收到任何内容时回退到 complete()。
        """
        endpoint = self._chat_endpoint()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            stream=True,
            timeout=timeout or self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"大模型调用失败 HTTP {resp.status_code}: {resp.text[:300]}"
            )

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue  # SSE 注释行 / 心跳行，忽略
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue  # 极少数厂商会插非 JSON 心跳包，跳过即可
            try:
                delta = obj["choices"][0]["delta"].get("content")
            except (KeyError, IndexError, AttributeError):
                continue
            if delta:
                yield delta


class EmbeddingClient:
    def __init__(self):
        self.base_url = Config.EMBED_BASE_URL
        self.api_key = Config.EMBED_API_KEY
        self.model = Config.EMBED_MODEL
        self.dim = Config.EMBED_DIM

    def _endpoint(self):
        base = (self.base_url or "").rstrip("/")
        if not base or "your-embed" in base:
            raise ValueError(
                "EMBED_BASE_URL 未正确配置（请在 .env 填写阿里云百炼兼容模式地址，"
                "例如 https://dashscope.aliyuncs.com/compatible-mode/v1）"
            )
        return base + "/embeddings"

    # 阿里云百炼兼容模式的硬限制：单次请求的 input 数组不能超过 10 条，
    # 超了会报 400 "batch size is invalid, it should not be larger than 10"。
    # 资料切出的片段经常几十上百个，必须分批。
    MAX_BATCH = 10

    def embed(self, texts):
        """texts: List[str] → List[List[float]]，顺序与输入一致（自动分批）。"""
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return []
        out = []
        for i in range(0, len(texts), self.MAX_BATCH):
            out.extend(self._embed_batch(texts[i:i + self.MAX_BATCH]))
        return out

    def _embed_batch(self, texts):
        payload = {"model": self.model, "input": texts}
        if self.dim:
            payload["dimensions"] = self.dim
        resp = requests.post(
            self._endpoint(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Embedding 调用失败 {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()["data"]
        # 按 index 排序，保证与输入顺序一致
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]


# 模块级单例（与 services/vector_store.py 的 vector_store 用法一致）
llm_client = LLMClient()
embedding_client = EmbeddingClient()
