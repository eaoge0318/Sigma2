"""
RAG Router - 歷史知識庫管理
POST /api/rag/index-notebook  — 將筆記本存入歷史知識庫
GET  /api/rag/documents       — 列出知識庫內容
DELETE /api/rag/document      — 刪除指定來源
POST /api/rag/query           — 直接查詢（測試用）
"""
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
import config

_thread_pool = ThreadPoolExecutor(max_workers=4)

from backend.services import rag_service

router = APIRouter(tags=["RAG - 歷史知識庫"])
logger = logging.getLogger(__name__)


class IndexNotebookRequest(BaseModel):
    session_id: str
    file_stem: str
    label: Optional[str] = None  # 顯示名稱，預設用 file_stem
    notes: List[Dict[str, Any]]
    user_id: str = "default"


@router.post("/index-notebook")
async def index_notebook(req: IndexNotebookRequest):
    """將筆記本存入歷史知識庫（覆蓋同名來源）"""
    try:
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(
            _thread_pool,
            lambda: rag_service.index_notebook_notes(
                notes=req.notes,
                session_id=req.session_id,
                file_stem=req.file_stem,
                label=req.label,
                user_id=req.user_id,
            )
        )
        logger.info(f"[RAG] ✓ 筆記本存入完成 user={req.user_id} label='{req.label}' indexed={count}")
        return {"ok": True, "indexed": count}
    except Exception as e:
        logger.error(f"[RAG] ✗ index_notebook 失敗 user={req.user_id} label='{req.label}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents")
async def list_documents(user_id: str = Query("default")):
    """列出歷史知識庫中所有來源"""
    try:
        items = rag_service.get_indexed_items(user_id=user_id)
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/all")
async def delete_all_documents(user_id: str = Query("default")):
    """清除該 user 知識庫的全部資料"""
    try:
        count = rag_service.clear_all_documents(user_id=user_id)
        return {"ok": True, "deleted": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/document/folder")
async def move_document_folder(
    label: str = Query(..., description="來源標籤"),
    folder: str = Query("", description="目標資料夾（空字串 = 未分類）"),
    user_id: str = Query("default"),
):
    """將文件移到指定資料夾"""
    try:
        result = rag_service.update_document_folder(label, folder, user_id=user_id)
        return {"ok": True, "updated": result["count"], "new_label": result["new_label"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/document")
async def delete_document(
    label: str = Query(..., description="來源標籤"),
    user_id: str = Query("default"),
):
    """從歷史知識庫刪除指定來源"""
    try:
        count = rag_service.delete_by_label(label, user_id=user_id)
        logger.info(f"[RAG] ✓ 刪除完成 user={user_id} label='{label}' deleted={count}")
        return {"ok": True, "deleted": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    user_id: str = Form("default"),
    folder: str = Form(""),
):
    """
    批次上傳文件並索引入歷史知識庫。
    支援：.pdf .docx .txt .md
    PDF：文字 + 圖片雙索引
    DOCX：文字索引（圖片 Phase 2）
    TXT/MD：文字索引
    """
    from backend.services import pdf_ingestor, docx_ingestor, pptx_ingestor, xlsx_ingestor
    from pathlib import Path

    results = []
    loop = asyncio.get_event_loop()

    for file in files:
        filename = file.filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        try:
            raw = await file.read()

            # 儲存原始文件到 workspace/{user_id}/docs/{folder}/{filename}
            user_base = Path("workspace") / user_id
            docs_dir = user_base / "docs" / Path(folder) if folder else user_base / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / filename).write_bytes(raw)

            def _process(raw=raw, ext=ext, filename=filename, uid=user_id, fld=folder):
                import time as _time
                t_start = _time.time()
                img_dir = str(Path("workspace") / uid / "images")
                if ext == "pdf":
                    parsed = pdf_ingestor.ingest_pdf(raw, filename, workspace_dir=img_dir)
                    t_parse = _time.time()
                    logger.info(f"[UPLOAD-TIMER] '{filename}' PDF解析: {t_parse-t_start:.2f}s")
                    counts = rag_service.index_parsed_document(parsed, user_id=uid, folder=fld)
                    logger.info(f"[UPLOAD-TIMER] '{filename}' 總計: {_time.time()-t_start:.2f}s  (解析{t_parse-t_start:.1f}s + embedding{_time.time()-t_parse:.1f}s)  chunks={counts['text_chunks']}")
                    return {"filename": filename, "ok": True, "text_chunks": counts["text_chunks"], "image_chunks": counts["image_chunks"]}
                elif ext == "docx":
                    parsed = docx_ingestor.ingest_docx(raw, filename)
                    counts = rag_service.index_parsed_document(parsed, user_id=uid, folder=fld)
                    logger.info(f"[UPLOAD-TIMER] '{filename}' 總計: {_time.time()-t_start:.2f}s  chunks={counts['text_chunks']}")
                    return {"filename": filename, "ok": True, "text_chunks": counts["text_chunks"], "image_chunks": counts["image_chunks"]}
                elif ext == "pptx":
                    parsed = pptx_ingestor.ingest_pptx(raw, filename)
                    counts = rag_service.index_parsed_document(parsed, user_id=uid, folder=fld)
                    logger.info(f"[UPLOAD-TIMER] '{filename}' 總計: {_time.time()-t_start:.2f}s  chunks={counts['text_chunks']}")
                    return {"filename": filename, "ok": True, "text_chunks": counts["text_chunks"], "image_chunks": counts["image_chunks"]}
                elif ext == "ppt":
                    return {"filename": filename, "ok": False, "reason": "不支援舊版 .ppt 格式，請在 PowerPoint 另存為 .pptx 或 .pdf 後再上傳"}
                elif ext == "xlsx":
                    parsed = xlsx_ingestor.ingest_xlsx(raw, filename)
                    counts = rag_service.index_parsed_document(parsed, user_id=uid, folder=fld)
                    logger.info(f"[UPLOAD-TIMER] '{filename}' 總計: {_time.time()-t_start:.2f}s  chunks={counts['text_chunks']}")
                    return {"filename": filename, "ok": True, "text_chunks": counts["text_chunks"], "image_chunks": counts["image_chunks"]}
                elif ext == "xls":
                    return {"filename": filename, "ok": False, "reason": "不支援舊版 .xls 格式，請在 Excel 另存為 .xlsx 或 .csv 後再上傳"}
                elif ext in ("txt", "md", "csv"):
                    text = _extract_plain_text(raw, filename)
                    if not text.strip():
                        return {"filename": filename, "ok": False, "reason": "無法擷取文字內容"}
                    chunks = rag_service.chunk_text(text)
                    count = rag_service.index_document_chunks(
                        chunks=chunks, filename=filename, source_type="document", user_id=uid, folder=fld
                    )
                    logger.info(f"[UPLOAD-TIMER] '{filename}' 總計: {_time.time()-t_start:.2f}s  chunks={count}")
                    return {"filename": filename, "ok": True, "text_chunks": count, "image_chunks": 0}
                else:
                    return {"filename": filename, "ok": False, "reason": f"不支援格式 .{ext}"}

            result = await loop.run_in_executor(_thread_pool, _process)
            results.append(result)
        except Exception as e:
            logger.error(f"[RAG] upload {filename} error: {e}", exc_info=True)
            results.append({"filename": filename, "ok": False, "reason": str(e)})

    return {"results": results}


def _extract_plain_text(raw: bytes, filename: str) -> str:
    """純文字檔（txt / md / csv）編碼自動偵測"""
    for enc in ("utf-8", "utf-8-sig", "big5", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


class QueryRequest(BaseModel):
    query: str
    top_k: int = 3
    threshold: float = 0.4
    user_id: str = "default"


class ImportWebRequest(BaseModel):
    url: str
    user_id: str = "default"
    folder: str = ""


class SearchWebRequest(BaseModel):
    query: str
    user_id: str = "default"
    folder: str = ""
    max_results: int = 5
    domains: List[str] = []




@router.get("/document-detail")
async def get_document_detail(
    label: str = Query(..., description="來源標籤"),
    user_id: str = Query("default"),
):
    """取得單一來源的文字段落 + 圖片清單"""
    try:
        detail = rag_service.get_document_detail(label, user_id=user_id)
        return detail
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
async def query_rag(req: QueryRequest):
    """直接查詢歷史知識庫（測試 / 除錯用）"""
    try:
        results = rag_service.query_similar(
            query_text=req.query,
            top_k=req.top_k,
            threshold=req.threshold,
            user_id=req.user_id,
        )
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import-web")
async def import_web(req: ImportWebRequest):
    """抓取公開網頁內容，轉成文字後寫入知識庫。"""
    from pathlib import Path
    from backend.services import web_ingestor

    try:
        loop = asyncio.get_event_loop()

        def _run():
            user_base = Path("workspace") / req.user_id
            parsed = web_ingestor.fetch_web_document(
                url=req.url,
                workspace_dir=str(user_base),
                folder=req.folder,
            )
            label = f"{req.folder}/{parsed['filename']}" if req.folder else parsed["filename"]
            count = rag_service.index_document_chunks(
                chunks=rag_service.chunk_text(parsed["text"]),
                filename=parsed["filename"],
                label=label,
                source_type="web",
                user_id=req.user_id,
                folder=req.folder,
                extra_metadata={
                    "source_name": parsed["title"],
                    "source_url": parsed["final_url"],
                    "content_type": parsed["content_type"],
                },
            )
            return {
                "ok": True,
                "label": label,
                "source_name": parsed["title"],
                "source_url": parsed["final_url"],
                "text_chunks": count,
            }

        return await loop.run_in_executor(_thread_pool, _run)
    except Exception as e:
        logger.error(f"[RAG] import_web error url={req.url}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/search-web")
async def search_web(req: SearchWebRequest):
    """依照主題搜尋外部資料（中英雙語），先回傳候選結果供使用者確認。"""
    from backend.services import web_search_service

    try:
        loop = asyncio.get_event_loop()

        def _run():
            return web_search_service.search_web_bilingual(
                query=req.query,
                max_results=req.max_results,
                allowed_domains=req.domains,
            )

        result = await loop.run_in_executor(_thread_pool, _run)
        candidates = result["results"]
        return {
            "ok": True,
            "query": req.query,
            "translated_query": result.get("translated_query"),
            "searched": len(candidates),
            "fallback_used": result.get("fallback_used", False),
            "results": candidates,
            "count": len(candidates),
        }
    except Exception as e:
        logger.error(f"[RAG] search_web error query={req.query}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

