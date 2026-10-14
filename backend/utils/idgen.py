"""生成业务主键，形如 mat_3f9a1c2b。"""
import uuid


def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"
