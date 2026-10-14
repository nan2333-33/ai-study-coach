"""语义切块：按段落 / 句子边界切分，目标 500-800 字，保留来源页码。

输入：List[PageText]；输出：List[Chunk]。
- 尽量在段落、句子边界切，避免把一句话劈开（对应 PRD M-03「语义切块」）
- 每块记录来源页码（最后一段所在页），供对话引用（M-05）
- 单段超长时按句子、再按字符兜底切分

对应 PRD M-03。
"""
import re

from config import Config
from services.extractors import PageText

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\.\n])")


class Chunk:
    def __init__(self, chunk_index: int, page_number: int, content: str):
        self.chunk_index = chunk_index
        self.page_number = page_number
        self.content = content


def chunk_text(pages: list[PageText], min_size: int = None, max_size: int = None) -> list[Chunk]:
    min_size = min_size or Config.CHUNK_MIN
    max_size = max_size or Config.CHUNK_MAX

    # 逐页拆成非空段落，保留页码
    items = []  # (page_number, paragraph)
    for pg in pages:
        for para in re.split(r"\n\s*\n", pg.text):
            para = para.strip()
            if para:
                items.append((pg.page_number, para))

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_pages: list[int] = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_pages, buf_len
        if not buf:
            return
        content = "\n".join(buf)
        page_number = buf_pages[-1]
        chunks.append(Chunk(len(chunks), page_number, content))
        buf, buf_pages, buf_len = [], [], 0

    for page_no, para in items:
        # 单段超长：先 flush 缓冲区，再把这段单独切
        if len(para) > max_size:
            flush()
            for sub in _split_long(para, max_size):
                chunks.append(Chunk(len(chunks), page_no, sub))
            continue
        if buf and buf_len + len(para) + 1 >= max_size:
            flush()
        buf.append(para)
        buf_pages.append(page_no)
        buf_len += len(para) + 1

    flush()
    return chunks


def _split_long(para: str, max_size: int) -> list[str]:
    """超长段落：先按句子切，句子仍超长则硬切。"""
    parts = [p for p in _SENT_SPLIT.split(para) if p.strip()] or [para]
    out: list[str] = []
    cur = ""
    for p in parts:
        if len(cur) + len(p) <= max_size:
            cur += p
        else:
            if cur:
                out.append(cur)
            if len(p) > max_size:
                for i in range(0, len(p), max_size):
                    out.append(p[i : i + max_size])
                cur = ""
            else:
                cur = p
    if cur:
        out.append(cur)
    return out
