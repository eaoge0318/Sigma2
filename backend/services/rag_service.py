"""
RAG Service - ChromaDB 歷史知識庫
支援筆記本轉歷史資料、查詢相似案例
"""
import uuid
import time
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_chroma_client = None
_collection = None
_embed_model = None  # sentence-transformers model singleton


def _use_external_embed() -> bool:
    return bool(config.RAG_EMBEDDING_URL)


def _embed_via_tei(texts: list, batch_size: int = 32) -> list:
    """呼叫外部 text-embeddings-inference 服務（POST /embed），分批避免 413"""
    import requests
    url = config.RAG_EMBEDDING_URL.rstrip("/") + "/embed"
    results = []
    
    i = 0
    current_batch_size = batch_size
    while i < len(texts):
        batch = texts[i: i + current_batch_size]
        try:
            resp = requests.post(url, json={"inputs": batch, "normalize": True}, timeout=60)
            
            if resp.status_code == 413:
                if current_batch_size > 1:
                    current_batch_size = max(1, current_batch_size // 2)
                    logger.warning(f"[RAG] 413 Payload Too Large，降低 batch_size 至 {current_batch_size} 重試...")
                    continue
                else:
                    logger.warning(f"[RAG] 單一文本仍引發 413，進行截斷重試 (目前長度: {len(batch[0])})")
                    texts[i] = batch[0][:len(batch[0]) // 2]
                    continue
            
            resp.raise_for_status()
            
            batch_res = resp.json()
            if isinstance(batch_res, list):
                results.extend(batch_res)
            i += len(batch)
            
        except requests.exceptions.RequestException as e:
            # For 413, if it somehow threw RequestException early, we catch and retry if it's explicitly 413
            if getattr(e.response, "status_code", None) == 413:
                if current_batch_size > 1:
                    current_batch_size = max(1, current_batch_size // 2)
                    logger.warning(f"[RAG] (Exception) 413 Payload Too Large，降低 batch_size 至 {current_batch_size} 重試...")
                    continue
                else:
                    logger.warning(f"[RAG] (Exception) 單一文本仍引發 413，截斷重試 (目前長度: {len(batch[0])})")
                    texts[i] = batch[0][:len(batch[0]) // 2]
                    continue
            raise e

    return results


def _get_embed_model():
    """Lazy-load embedding model（singleton），有 GPU 時自動使用"""
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        t0 = time.time()
        device = None
        if config.RAG_USE_GPU:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        _embed_model = SentenceTransformer(config.RAG_EMBEDDING_MODEL, device=device)
        actual_device = str(_embed_model.device)
        logger.info(f"[RAG-TIMER] model='{config.RAG_EMBEDDING_MODEL}' device={actual_device} 載入: {time.time()-t0:.2f}s")
    return _embed_model


def _embed_documents(texts: list) -> list:
    """Index 端 embedding（e5 加 'passage: ' 前綴）"""
    is_e5 = "e5" in config.RAG_EMBEDDING_MODEL.lower()
    if _use_external_embed():
        prefixed = [f"passage: {t}" for t in texts] if is_e5 else texts
        return _embed_via_tei(prefixed)
    if is_e5:
        texts = [f"passage: {t}" for t in texts]
    return _get_embed_model().encode(texts, normalize_embeddings=True).tolist()


def _embed_query(text: str) -> list:
    """Query 端 embedding（e5 加 'query: ' 前綴）"""
    is_e5 = "e5" in config.RAG_EMBEDDING_MODEL.lower()
    if _use_external_embed():
        prefixed = f"query: {text}" if is_e5 else text
        return _embed_via_tei([prefixed])
    t = f"query: {text}" if is_e5 else text
    return _get_embed_model().encode([t], normalize_embeddings=True).tolist()


def _get_collection(user_id: str = "default"):
    """取得（或初始化）ChromaDB collection，每個 user 獨立 collection"""
    global _chroma_client, _collection

    # 初始化 client（singleton）
    if _chroma_client is None:
        import chromadb
        path = Path(config.RAG_CHROMA_PATH)
        path.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(path))

    # collection 名稱依 user_id 區分
    safe_uid = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)[:40]
    col_name = f"{config.RAG_COLLECTION_PREFIX}_{safe_uid}"

    if _collection is not None and getattr(_collection, "_name", None) == col_name:
        return _collection

    from chromadb.utils import embedding_functions
    if _use_external_embed():
        from chromadb import EmbeddingFunction, Documents, Embeddings

        class _TEIEmbeddingFunction(EmbeddingFunction[Documents]):
            def __call__(self, input: Documents) -> Embeddings:
                return _embed_via_tei(list(input))
        ef = _TEIEmbeddingFunction()
    else:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.RAG_EMBEDDING_MODEL
        )
    _collection = _chroma_client.get_or_create_collection(
        name=col_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    _collection._name = col_name
    logger.info(f"[RAG] collection='{col_name}'，已有 {_collection.count()} 筆")
    return _collection


def index_notebook_notes(
    notes: List[Dict],
    session_id: str,
    file_stem: str,
    label: Optional[str] = None,
    user_id: str = "default",
) -> int:
    """
    將筆記本的 notes 存入歷史知識庫。
    每則 note 成為一個 chunk。
    回傳成功 index 的數量。
    """
    collection = _get_collection(user_id)

    label = label or file_stem

    # 先刪除同 label 的舊資料（避免重複）
    _delete_by_label(collection, label)

    documents = []
    metadatas = []
    ids = []

    for i, note in enumerate(notes):
        text = (note.get("text") or "").strip()
        if not text:
            continue

        tool = note.get("tool", "")
        timestamp = note.get("timestamp", "")

        # 組合文字：工具名稱 + 內容
        doc_text = f"【{tool}】\n{text}" if tool else text

        documents.append(doc_text)
        metadatas.append({
            "source_type": "notebook",
            "session_id": session_id,
            "file_stem": file_stem,
            "note_index": i,
            "tool": tool,
            "timestamp": timestamp,
            "label": label,
        })
        ids.append(str(uuid.uuid4()))

    if documents:
        collection.add(documents=documents, metadatas=metadatas, ids=ids)
        logger.info(f"[RAG] 筆記本 '{label}' 已存入 {len(documents)} 則筆記")

    return len(documents)


def query_similar(
    query_text: str,
    top_k: Optional[int] = None,
    threshold: Optional[float] = None,
    user_id: str = "default",
) -> List[Dict[str, Any]]:
    """
    根據 query_text 查詢歷史知識庫，回傳相似度超過閾值的 chunks。

    回傳格式：
    [
        {
            "content": str,
            "source_name": str,
            "source_type": str,   # "notebook" | "document"
            "location": str,
            "score": float,
        },
        ...
    ]
    """
    if top_k is None:
        top_k = config.RAG_TOP_K
    if threshold is None:
        threshold = config.RAG_SIMILARITY_THRESHOLD

    collection = _get_collection(user_id)
    count = collection.count()
    if count == 0:
        return []

    try:
        t0 = time.time()
        query_embedding = _embed_query(query_text)
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, count),
            include=["documents", "metadatas", "distances"],
        )
        logger.info(f"[RAG-TIMER] ChromaDB query（含 embedding）: {time.time()-t0:.2f}s")
    except Exception as e:
        logger.error(f"[RAG] 查詢失敗: {e}")
        return []

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    chunks = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        # cosine distance → similarity（距離越小越相似）
        similarity = 1.0 - dist
        if similarity < threshold:
            continue

        source_type = meta.get("source_type", "document")
        if source_type == "notebook":
            source_name = meta.get("label", meta.get("file_stem", "筆記本"))
            tool = meta.get("tool", "")
            ts = meta.get("timestamp", "")
            location = f"{tool}" + (f" | {ts}" if ts else "")
        else:
            # 相容 pdf_ingestor（存 source_name）和 index_document_chunks（存 filename）
            source_name = (meta.get("source_name")
                           or meta.get("label")
                           or meta.get("filename")
                           or "文件")
            page = meta.get("page", "")
            location = meta.get("source_url", "") if source_type == "web" else (f"第 {page} 頁" if page else "")

        chunks.append({
            "content": doc,
            "source_name": source_name,
            "source_type": source_type,
            "location": location,
            "score": round(similarity, 3),
        })

    return chunks


def get_indexed_items(user_id: str = "default") -> List[Dict]:
    """列出知識庫中所有來源（按 label 分組）"""
    collection = _get_collection(user_id)
    count = collection.count()
    if count == 0:
        return []

    results = collection.get(include=["metadatas"])
    metadatas = results.get("metadatas", [])

    groups: Dict[str, Dict] = {}
    for meta in metadatas:
        label = meta.get("label") or meta.get("filename") or "unknown"
        if label not in groups:
            groups[label] = {
                "label": label,
                "source_name": meta.get("source_name", ""),
                "source_url": meta.get("source_url", ""),
                "source_type": meta.get("source_type", "unknown"),
                "folder": meta.get("folder", ""),
                "count": 0,
            }
        groups[label]["count"] += 1

    return list(groups.values())


def index_document_chunks(
    chunks: List[str],
    filename: str,
    label: Optional[str] = None,
    source_type: str = "document",
    user_id: str = "default",
    folder: str = "",
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    將文件 chunks 存入歷史知識庫。
    label 預設用 filename。
    """
    collection = _get_collection(user_id)
    label = label or (f"{folder}/{filename}" if folder else filename)

    _delete_by_label(collection, label)

    documents, metadatas, ids = [], [], []
    base_meta = extra_metadata or {}
    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        documents.append(chunk)
        meta = {
            "source_type": source_type,
            "filename": filename,
            "label": label,
            "file_path": label,   # folder/filename 或 filename
            "chunk_index": i,
            "page": "",
            "folder": folder,
        }
        meta.update(base_meta)
        metadatas.append(meta)
        ids.append(str(uuid.uuid4()))

    if documents:
        t0 = time.time()
        collection.add(documents=documents, metadatas=metadatas, ids=ids)
        logger.info(f"[RAG-TIMER] '{filename}' embedding+寫入 ChromaDB: {time.time()-t0:.2f}s，chunks={len(documents)}")

    return len(documents)


def index_parsed_document(parsed: Dict[str, Any], user_id: str = "default", folder: str = "") -> Dict[str, int]:
    """
    將 ingestor 輸出的 text_chunks 存入 ChromaDB。
    圖片只存磁碟（由 ingestor 負責），不進 ChromaDB。
    """
    collection = _get_collection(user_id)
    filename = parsed["filename"]
    label = f"{folder}/{filename}" if folder else filename

    _delete_by_label(collection, label)

    all_docs, all_metas, all_ids = [], [], []

    for chunk in parsed.get("text_chunks", []):
        if not chunk["content"].strip():
            continue
        meta = {**chunk["metadata"]}
        meta["label"] = label
        meta["file_path"] = label   # folder/filename 或 filename
        meta["source_type"] = "document"
        meta["doc_type"] = "text_chunk"
        meta["folder"] = folder
        meta = {k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
                for k, v in meta.items()}
        all_docs.append(chunk["content"])
        all_metas.append(meta)
        all_ids.append(chunk["id"])

    import time
    t0 = time.time()
    BATCH = 50  # 每批 50 個 chunk，避免大檔 OOM
    for i in range(0, len(all_docs), BATCH):
        collection.add(
            documents=all_docs[i:i+BATCH],
            metadatas=all_metas[i:i+BATCH],
            ids=all_ids[i:i+BATCH],
        )
    t1 = time.time()

    total_images = parsed.get("manifest", {}).get("total_images", 0)
    result = {
        "text_chunks": len(all_docs),
        "image_chunks": total_images,
    }
    logger.info(f"[RAG-TIMER] '{filename}' embedding+寫入 ChromaDB: {t1-t0:.2f}s，chunks={len(all_docs)}")
    return result


def get_document_detail(label: str, user_id: str = "default") -> Dict[str, Any]:
    """
    取得單一來源的完整資料：
    - text_chunks: 文字段落（依頁碼排序）
    - images: 磁碟上對應的圖片檔（依頁碼排序，含 URL）
    - doc_id: 文件識別碼
    """
    collection = _get_collection(user_id)
    results = collection.get(
        where={"label": label},
        include=["documents", "metadatas"],
        limit=500,
    )

    text_chunks: list = []
    doc_id: Optional[str] = None
    file_path: Optional[str] = None
    source_name: str = ""
    source_url: str = ""

    for doc, meta in zip(results.get("documents", []), results.get("metadatas", [])):
        dt = meta.get("doc_type", "text_chunk")
        if dt == "text_chunk":
            text_chunks.append({
                "page": meta.get("page", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "content": doc,
            })
            # 從 text_chunk 取 doc_id（圖片目錄由此推算）
            if doc_id is None:
                doc_id = meta.get("doc_id")
            if file_path is None:
                file_path = meta.get("file_path")
            if not source_name:
                source_name = meta.get("source_name", "")
            if not source_url:
                source_url = meta.get("source_url", "")

    text_chunks.sort(key=lambda x: (x.get("page") or 0, x.get("chunk_index") or 0))

    # 掃描圖片目錄（圖片只存磁碟，不在 ChromaDB）
    images: list = []
    if doc_id:
        image_dir_path = Path("workspace") / user_id / "images" / doc_id
        if image_dir_path.exists():
            for f in sorted(image_dir_path.iterdir()):
                if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                    continue
                page_num = 0
                try:
                    page_num = int(f.stem.split("_")[0][1:])
                except Exception:
                    pass
                images.append({
                    "page": page_num,
                    "filename": f.name,
                    "url": f"/workspace/{user_id}/images/{doc_id}/{f.name}",
                })

    return {
        "label": label,
        "source_name": source_name or label,
        "source_url": source_url,
        "file_path": file_path or label,  # 舊資料 fallback 用 label
        "doc_id": doc_id,
        "text_chunks": text_chunks,
        "images": images,
    }


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> List[str]:
    """將長文字切成有重疊的 chunks"""
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
        # 嘗試在句尾斷開
        for sep in ["。", "！", "？", "\n", ".", "!", "?"]:
            last = raw_chunk.rfind(sep)
            if last > chunk_size // 2:
                raw_chunk = raw_chunk[:last + 1]
                break
        advance = max(len(raw_chunk) - overlap, 1)  # 確保 start 一定往前
        chunks.append(raw_chunk.strip())
        start += advance
    return [c for c in chunks if c]


def update_document_folder(label: str, folder: str, user_id: str = "default") -> Dict[str, Any]:
    """將指定 label 的所有 chunks 移到新資料夾（含磁碟檔案搬移）"""
    collection = _get_collection(user_id)
    try:
        results = collection.get(where={"label": label}, include=["metadatas"])
        ids = results.get("ids", [])
        if not ids:
            return {"count": 0, "new_label": label}

        # 從 metadata 取得原始檔名（不含路徑）
        old_meta = results.get("metadatas", [{}])[0]
        old_file_path = old_meta.get("file_path", label)
        filename = old_meta.get("source_name") or old_meta.get("filename") or Path(old_file_path).name
        new_file_path = f"{folder}/{filename}" if folder else filename
        new_label = new_file_path

        # 搬移磁碟原始檔（若存在）
        docs_base = Path("workspace") / user_id / "docs"
        old_disk = docs_base / old_file_path
        new_disk = docs_base / new_file_path
        if old_disk.exists() and old_disk.resolve() != new_disk.resolve():
            new_disk.parent.mkdir(parents=True, exist_ok=True)
            old_disk.rename(new_disk)
            logger.info(f"[RAG] 磁碟搬移 '{old_disk}' → '{new_disk}'")

        # 更新 ChromaDB metadata
        new_metas = []
        for meta in results.get("metadatas", []):
            m = dict(meta)
            m["folder"] = folder
            m["file_path"] = new_file_path
            m["label"] = new_label
            new_metas.append(m)
        collection.update(ids=ids, metadatas=new_metas)
        logger.info(f"[RAG] 移動 '{label}' → '{new_label}'，共 {len(ids)} 筆")
        return {"count": len(ids), "new_label": new_label}
    except Exception as e:
        logger.warning(f"[RAG] update_document_folder 失敗: {e}")
        return {"count": 0, "new_label": label}


def delete_by_label(label: str, user_id: str = "default") -> int:
    """從知識庫刪除指定 label 的所有資料"""
    collection = _get_collection(user_id)
    return _delete_by_label(collection, label)


def clear_all_documents(user_id: str = "default") -> int:
    """清除該 user 知識庫的全部資料（刪除 collection 再重建）"""
    global _chroma_client, _collection
    if _chroma_client is None:
        return 0
    safe_uid = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)[:40]
    col_name = f"{config.RAG_COLLECTION_PREFIX}_{safe_uid}"
    try:
        col = _chroma_client.get_collection(col_name)
        count = col.count()
        _chroma_client.delete_collection(col_name)
        _collection = None  # 清快取，下次重建
        logger.info(f"[RAG] 已清除全部 user={user_id} col={col_name} 共 {count} 筆")
        return count
    except Exception as e:
        logger.warning(f"[RAG] clear_all 失敗: {e}")
        return 0


def _delete_by_label(collection, label: str) -> int:
    """內部：刪除指定 label 的資料"""
    try:
        results = collection.get(where={"label": label}, include=["metadatas"])
        ids = results.get("ids", [])
        if ids:
            collection.delete(ids=ids)
            logger.info(f"[RAG] 已刪除 '{label}' 共 {len(ids)} 筆")
        return len(ids)
    except Exception as e:
        logger.warning(f"[RAG] 刪除 '{label}' 失敗: {e}")
        return 0
