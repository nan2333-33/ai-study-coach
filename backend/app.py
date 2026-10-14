"""AI 学习助手 —— Flask 后端入口。

启动：
    pip install -r requirements.txt
    cp .env.example .env   # 填入 LLM / Embedding 的 URL 与 KEY
    python app.py          # 默认 http://127.0.0.1:5000
"""
import os
import re
import sys

# 确保 backend 目录在 sys.path，子模块（config / models / ...）可直接绝对导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request
from flask_cors import CORS
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config
from models import Base
from models.quiz import ensure_order_index_column
from models.knowledge import ensure_canonical_id_column
from models.report import ensure_question_count_column
from routes import register_routes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(Config.UPLOAD_DIR, exist_ok=True)
os.makedirs(Config.CHROMA_DIR, exist_ok=True)

# 本机来源：localhost / 127.0.0.1 的任意端口一律放行。
# 白名单写死单个地址（如只允许 http://127.0.0.1:8123）会导致：用户换成 localhost
# 打开、或前端临时换端口，浏览器就拿不到 Allow-Origin 而拦截全部接口，
# 页面表现为「资料不见了」——实际数据一个没丢，纯跨域问题。这里是本地自托管应用，
# 不存在跨站风险，所以直接对本机全放行。
_LOCAL_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", re.I)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    origins = "*" if "*" in Config.CORS_ORIGINS else Config.CORS_ORIGINS
    CORS(app, origins=origins)

    @app.after_request
    def _allow_local_origin(resp):
        """补齐本机来源的跨域头（flask-cors 只按白名单精确匹配，漏掉的会被浏览器拦）。"""
        origin = request.headers.get("Origin", "")
        if origin and _LOCAL_ORIGIN_RE.match(origin):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
            resp.headers["Vary"] = "Origin"
        return resp

    # 数据库：建表（MVP 用 SQLite；切换 PostgreSQL 改 DB_URL 即可）
    engine_kwargs = {}
    if Config.DB_URL.startswith("sqlite"):
        # 允许后台处理线程与请求线程共享同一 SQLite 文件
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(Config.DB_URL, future=True, **engine_kwargs)
    Base.metadata.create_all(engine)
    ensure_order_index_column(engine)  # 老库补列 + 回填出题顺序（建表不会自动加列）
    ensure_question_count_column(engine)  # 老库补列：周报主指标由「学习时长」换成「答题数」
    ensure_canonical_id_column(engine)  # 老库补列：知识点语义聚类后的代表 id
    app.engine = engine
    app.SessionLocal = sessionmaker(bind=engine, future=True)

    register_routes(app)
    return app


if __name__ == "__main__":
    app = create_app()
    # use_reloader=False 必须关：热重载会重复加载模块，导致向量库 collection
    # 被反复重建（UUID 变化），正在跑的解析线程会拿到失效引用而失败
    app.run(host="0.0.0.0", port=Config.PORT, debug=True, use_reloader=False)
