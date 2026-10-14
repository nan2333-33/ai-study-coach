from . import Base
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    UniqueConstraint,
    func,
)
from sqlalchemy.types import JSON


class Material(Base):
    """表1：资料表"""

    __tablename__ = "materials"
    id = Column(String(36), primary_key=True)
    title = Column(String(200), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    category = Column(String(100))
    status = Column(String(20), nullable=False, default="processing")
    chunk_count = Column(Integer, default=0)
    total_pages = Column(Integer)
    error_message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class MaterialChunk(Base):
    """表2：资料分块表"""

    __tablename__ = "material_chunks"
    __table_args__ = (
        UniqueConstraint("material_id", "chunk_index", name="uq_material_chunk"),
    )
    id = Column(String(36), primary_key=True)
    material_id = Column(String(36), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer)
    content = Column(Text, nullable=False)
    # MVP: SQLite 下以 JSON 数组存储；切换 PostgreSQL+pgvector 时改为 VECTOR(EMBED_DIM)
    embedding = Column(JSON)
    token_count = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())


class MaterialNote(Base):
    """表13：资料笔记表"""

    __tablename__ = "material_notes"
    id = Column(String(36), primary_key=True)
    material_id = Column(String(36), nullable=False, unique=True)
    content = Column(Text, nullable=False, default="")
    content_length = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
