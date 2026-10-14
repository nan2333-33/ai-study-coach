"""全局配置：从 .env 读取，环境变量缺省时回退到开发默认值。

两组模型完全独立配置：
- LLM_*      : 大模型（对话 / 出题 / 批改）
- EMBED_*    : 向量模型（文本嵌入）
"""
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_DB_URL = "sqlite:///" + os.path.join(DATA_DIR, "app.db")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    PORT = int(os.getenv("PORT", "5000"))
    CORS_ORIGINS = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
    ]

    # 数据库：默认 SQLite（零安装即可运行）。
    # 生产可改为 PostgreSQL：postgresql+psycopg://user:pass@host:5432/db
    _db = os.getenv("DB_URL", DEFAULT_DB_URL)
    # SQLite 相对路径统一解析到 backend/ 目录下，避免依赖启动目录
    if _db.startswith("sqlite:///"):
        _rel = _db[len("sqlite:///"):].lstrip("/")
        _db = "sqlite:///" + os.path.join(BASE_DIR, _rel)
    DB_URL = _db

    # 大模型（对话 / 出题 / 批改）—— 与向量模型互不干扰
    # 兼容 OpenAI Chat Completions 格式，默认对接 DeepSeek：
    #   LLM_BASE_URL = https://api.deepseek.com/v1
    #   LLM_MODEL    = deepseek-chat
    LLM_BASE_URL = os.getenv("LLM_BASE_URL")
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_MODEL = os.getenv("LLM_MODEL")
    # 大模型调用容错：网络异常 / 非 200 时自动重试次数（最多重试 3 次 = 共 4 次尝试）
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "90"))  # 单次调用超时（秒）

    # 向量模型（文本嵌入）
    EMBED_BASE_URL = os.getenv("EMBED_BASE_URL")
    EMBED_API_KEY = os.getenv("EMB_API_KEY")
    EMBED_MODEL = os.getenv("EMBED_MODEL")
    EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))

    # 上传与处理参数
    UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", "50"))   # M-01 单文件上限
    CHUNK_MIN = int(os.getenv("CHUNK_MIN", "500"))          # M-03 分块下限（字）
    CHUNK_MAX = int(os.getenv("CHUNK_MAX", "800"))          # M-03 分块上限（字）

    # 检索参数
    RETRIEVE_MIN_SCORE = float(os.getenv("RETRIEVE_MIN_SCORE", "0.15"))  # 余弦相似度下限，过低直接丢弃
    RETRIEVE_TOP_K = int(os.getenv("RETRIEVE_TOP_K", "8"))

    # 存储目录
    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
    CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
