"""
PDF Ingestor - PyMuPDF 版
文字抽取 + 圖片抽取，輸出統一格式的 text_chunks / image_chunks
"""
import io
import uuid
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


def ingest_pdf(raw: bytes, filename: str, workspace_dir: str = "workspace/images") -> Dict[str, Any]:
    """
    解析 PDF（PyMuPDF）：
    - text_chunks  → 進 ChromaDB（語意搜尋用）
    - 圖片         → 只存磁碟，不進 ChromaDB（供後續圖片比對）
    回傳格式：
    {
        "doc_id":       str,
        "filename":     str,
        "text_chunks":  [...],
        "image_chunks": [],       # 永遠為空，不進 ChromaDB
        "image_dir":    str,
        "manifest":     {...}
    }
    """
    import fitz  # PyMuPDF

    doc_id = uuid.uuid4().hex[:12]
    t0 = time.time()

    doc = fitz.open(stream=raw, filetype="pdf")
    total_pages = len(doc)
    t1 = time.time()
    logger.info(f"[PDF-TIMER] '{filename}' 共 {total_pages} 頁，fitz.open: {t1-t0:.2f}s")

    text_chunks = _extract_text_chunks(doc, filename, doc_id)
    t2 = time.time()
    logger.info(f"[PDF-TIMER] 文字抽取: {t2-t1:.2f}s，chunks={len(text_chunks)}")

    image_count, image_dir = _save_images(doc, filename, doc_id, workspace_dir)
    t3 = time.time()
    logger.info(f"[PDF-TIMER] 圖片存磁碟: {t3-t2:.2f}s，共 {image_count} 張")
    logger.info(f"[PDF-TIMER] 合計 ingest: {t3-t0:.2f}s")

    doc.close()

    return {
        "doc_id":       doc_id,
        "filename":     filename,
        "text_chunks":  text_chunks,
        "image_chunks": [],
        "image_dir":    image_dir,
        "manifest": {
            "total_pages":       total_pages,
            "total_text_chunks": len(text_chunks),
            "total_images":      image_count,
        },
    }


# ── Text ──────────────────────────────────────────────────────────────────────

def _extract_text_chunks(
    doc, filename: str, doc_id: str,
    chunk_size: int = 600, overlap: int = 80
) -> List[Dict[str, Any]]:
    """
    用 get_text("blocks") 抽取段落，保留 layout 資訊後切 chunk。
    每個 block 是一個自然段落，比按字元硬切更語意完整。
    """
    chunks = []
    chunk_idx = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_label = page_num + 1  # 1-based

        # blocks: (x0, y0, x1, y1, text, block_no, block_type)
        # block_type 0 = text, 1 = image
        blocks = page.get_text("blocks")
        page_text_parts = [
            b[4].strip()
            for b in blocks
            if b[6] == 0 and b[4].strip()  # block_type==0: text
        ]

        if not page_text_parts:
            continue

        # 合併同頁文字，再依 chunk_size 切割
        full_text = "\n".join(page_text_parts)
        for piece in _split_text(full_text, chunk_size, overlap):
            chunk_id = f"{doc_id}_p{page_label}_c{chunk_idx}"
            chunks.append({
                "id": chunk_id,
                "doc_type": "text_chunk",
                "content": piece,
                "metadata": {
                    "source_name": filename,
                    "page":        page_label,
                    "chunk_index": chunk_idx,
                    "file_type":   "pdf",
                    "doc_id":      doc_id,
                },
            })
            chunk_idx += 1

    return chunks


def _split_text(text: str, chunk_size: int = 600, overlap: int = 80) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    min_advance = chunk_size // 4  # 最小步長，避免 advance=1 的無限迴圈

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]

        # 從中點之後尋找斷句點（rfind 從 midpoint 往後找）
        cut = end - start
        for sep in ["。", "！", "？", "\n\n", "\n", ".", "!", "?"]:
            last = chunk.rfind(sep, chunk_size // 2)
            if last != -1:
                cut = last + len(sep)
                break

        piece = chunk[:cut].strip()
        if piece:
            chunks.append(piece)

        # advance 基於切點位置，不用 stripped 長度；最小 min_advance
        advance = max(cut - overlap, min_advance)
        start += advance

    return chunks


# ── Images ────────────────────────────────────────────────────────────────────

def _save_images(
    doc, filename: str, doc_id: str, workspace_dir: str
) -> Tuple[int, str]:
    """
    將 PDF 所有頁的圖片存到磁碟（供後續圖片比對用）。
    不建立任何 ChromaDB chunk。
    回傳 (total_image_count, image_dir_str)。
    """
    img_dir = Path(workspace_dir) / doc_id
    img_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    seen_xrefs = set()  # 去重（同一圖片可能被多頁引用）

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_label = page_num + 1

        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext   = base_image["ext"]  # "png" / "jpeg" / "jp2" etc.
                if image_ext == "jpeg":
                    image_ext = "jpg"

                out_path = img_dir / f"p{page_label}_img{img_index}.{image_ext}"
                out_path.write_bytes(image_bytes)
                total += 1
            except Exception as e:
                logger.warning(f"[PDF] 圖片儲存失敗 p{page_label} img{img_index}: {e}")

    return total, str(img_dir)
