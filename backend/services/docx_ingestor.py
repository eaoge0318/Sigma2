"""
DOCX Ingestor (Phase 1: 文字為主，圖片 Phase 2 補上)
輸出與 pdf_ingestor 相同格式
"""
import io
import uuid
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def ingest_docx(raw: bytes, filename: str, workspace_dir: str = "workspace/images") -> Dict[str, Any]:
    """
    解析 Word 文件，回傳統一格式
    Phase 1：只做文字切 chunk
    Phase 2：補圖片抽取
    """
    import docx

    CHUNK_SIZE = 600
    OVERLAP = 80

    doc_id = uuid.uuid4().hex[:12]
    doc = docx.Document(io.BytesIO(raw))

    text_chunks = []
    buffer = ""
    chunk_index = 0

    def _flush_buffer(buf: str):
        nonlocal chunk_index
        for piece in _split_text(buf, CHUNK_SIZE, OVERLAP):
            text_chunks.append({
                "id": f"{doc_id}_c{chunk_index}",
                "doc_type": "text_chunk",
                "content": piece,
                "metadata": {
                    "source_name": filename,
                    "page": 0,
                    "chunk_index": chunk_index,
                    "file_type": "docx",
                    "doc_id": doc_id,
                },
            })
            chunk_index += 1

    for para in doc.paragraphs:
        txt = para.text.strip()
        if not txt:
            continue
        buffer += txt + "\n"
        if len(buffer) >= CHUNK_SIZE * 4:
            _flush_buffer(buffer)
            buffer = ""

    if buffer:
        _flush_buffer(buffer)

    logger.info(f"[DOCX] '{filename}' 完成：text_chunks={len(text_chunks)}，image_chunks=0 (Phase 2)")

    return {
        "doc_id": doc_id,
        "filename": filename,
        "text_chunks": text_chunks,
        "image_chunks": [],   # Phase 2
        "manifest": {
            "total_pages": 0,
            "total_text_chunks": len(text_chunks),
            "total_images": 0,
        },
    }


def _split_text(text: str, chunk_size: int = 600, overlap: int = 80) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        raw_chunk = text[start:end]
        for sep in ["。", "！", "？", "\n", ".", "!", "?"]:
            last = raw_chunk.rfind(sep)
            if last > chunk_size // 2:
                raw_chunk = raw_chunk[:last + 1]
                break
        advance = max(len(raw_chunk) - overlap, 1)  # 確保 start 一定往前
        chunk = raw_chunk.strip()
        if chunk:
            chunks.append(chunk)
        start += advance
    return chunks
