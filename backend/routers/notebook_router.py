"""
分析筆記本 Router
POST /api/notebook/chat   — 以筆記內容為上下文，與地端 LLM 串流對話
GET  /api/notebook/notes  — 載入筆記（依 session_id + file_name）
POST /api/notebook/notes  — 儲存筆記（每筆 note 存成獨立 JSON 檔）
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, validator
from typing import List, Dict, Any, Optional
from pathlib import Path
import httpx
import json
import re
import logging

import config

router = APIRouter(tags=["Notebook - 分析筆記本"])
logger = logging.getLogger(__name__)

BASE_DIR = Path(config.BASE_STORAGE_DIR)  # workspace/


def _stem_from_name(file_name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", Path(file_name).stem)[:80]


def _notes_dir(session_id: str, file_name: str) -> Path:
    """新格式目錄：workspace/{session_id}/notes/{file_stem}/"""
    return BASE_DIR / session_id / "notes" / _stem_from_name(file_name)


def _notes_dir_by_stem(session_id: str, stem: str) -> Path:
    return BASE_DIR / session_id / "notes" / stem


def _legacy_notes_path(session_id: str, stem: str) -> Path:
    """舊格式（向後相容）：workspace/{session_id}/notes/{stem}.json"""
    return BASE_DIR / session_id / "notes" / f"{stem}.json"


def _dataset_notes_dir(session_id: str, dataset_path: str) -> Optional[Path]:
    """
    子資料集筆記目錄，與 dataset_router 的儲存路徑一致：
      主資料集 (main)：workspace/{session_id}/notes/{file_stem}/
      子資料集       ：workspace/{session_id}/notes/{file_stem}/{subset_id}/
    """
    parts = [p for p in dataset_path.replace("\\", "/").split("/") if p]
    if len(parts) != 2:
        return None
    file_stem, subset_id = parts
    base = BASE_DIR / session_id / "notes" / file_stem
    return base if subset_id == "main" else base / subset_id


# ===== Request Models =====

class NoteItem(BaseModel):
    tool: str        # 來源工具名稱，例如 "多變量分析"
    text: str        # 筆記文字內容
    timestamp: Optional[str] = None
    imageData: Optional[List[str]] = None  # 圖表截圖 data URL 列表

    @validator("imageData", pre=True)
    def normalize_image_data(cls, v):
        """向後相容：舊資料的單一字串自動轉為 list"""
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        return [x for x in v if x] or None


class NotebookChatRequest(BaseModel):
    file_name: str                          # 對應的 CSV 檔名
    message: str                            # 使用者訊息
    notes: List[NoteItem] = []              # 目前所有筆記
    history: List[Dict[str, str]] = []      # 對話歷史 [{"role":"user","content":"..."}]
    images: List[str] = []                  # 完整 data URL 列表，例如 "data:image/jpeg;base64,..."
    process_context: Optional[str] = None  # 資料說明（背景、欄位代號、品質指標等）
    column_names: List[str] = []           # 資料集所有欄位名稱
    column_stats: Dict[str, Any] = {}      # 數值欄位統計 {col: {mean, std, min, max, median, count}}


class NotebookSaveRequest(BaseModel):
    session_id: str
    file_name: str = ""
    dataset_path: Optional[str] = None   # 子資料集路徑，e.g. "file_stem/subset_id"
    notes: List[NoteItem] = []
    proc_desc: Optional[str] = None   # 此檔案的資料說明


def _global_desc_path(session_id: str) -> Path:
    """全域資料說明：workspace/{session_id}/proc_desc.txt"""
    return BASE_DIR / session_id / "proc_desc.txt"


# ===== Notes Persistence =====

def _read_notes_from_dir(notes_dir: Path) -> tuple[list, Optional[str]]:
    """從目錄讀取所有 note_*.json，回傳 (notes_list, proc_desc)"""
    note_files = sorted(notes_dir.glob("note_*.json"), key=lambda x: x.name)
    notes = []
    for f in note_files:
        try:
            notes.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning(f"筆記讀取失敗 {f}: {e}")
    proc_desc_path = notes_dir / "_proc_desc.txt"
    proc_desc = proc_desc_path.read_text(encoding="utf-8") if proc_desc_path.exists() else None
    return notes, proc_desc


@router.get("/list")
async def list_notebooks(session_id: str = Query(...)):
    """列出 workspace/{session_id}/notes/ 下所有筆記（目錄或舊格式 JSON），回傳列表"""
    notes_root = BASE_DIR / session_id / "notes"
    if not notes_root.exists():
        return {"notebooks": []}
    items = []
    seen_stems = set()
    for p in sorted(notes_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_dir():
            count = len(list(p.glob("note_*.json")))
            items.append({"stem": p.name, "count": count})
            seen_stems.add(p.name)
        elif p.suffix == ".json" and p.stem not in seen_stems:
            # 舊格式 .json 檔（若同名目錄已存在則略過）
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                count = len(data.get("notes", []))
            except Exception:
                count = 0
            items.append({"stem": p.stem, "count": count})
    return {"notebooks": items}


@router.get("/notes")
async def load_notes(
    session_id: str = Query(...),
    file_name: str = Query(None),
    stem: str = Query(None),
    dataset_path: str = Query(None),
):
    """載入指定 session + 檔案的筆記（含 proc_desc）。可用 dataset_path、file_name 或 stem 指定。"""
    # 優先使用 dataset_path（新格式：子資料集）
    if dataset_path:
        ndir = _dataset_notes_dir(session_id, dataset_path)
        if ndir and ndir.is_dir():
            notes, proc_desc = _read_notes_from_dir(ndir)
            return {"notes": notes, "proc_desc": proc_desc}
        return {"notes": [], "proc_desc": None}

    if stem:
        resolved_stem = stem
        ndir = _notes_dir_by_stem(session_id, stem)
    elif file_name:
        resolved_stem = _stem_from_name(file_name)
        ndir = _notes_dir(session_id, file_name)
    else:
        return {"notes": [], "proc_desc": None}

    # 新格式：目錄
    if ndir.is_dir():
        notes, proc_desc = _read_notes_from_dir(ndir)
        return {"notes": notes, "proc_desc": proc_desc}

    # 舊格式：單一 JSON 檔（向後相容）
    legacy = _legacy_notes_path(session_id, resolved_stem)
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            return {"notes": data.get("notes", []), "proc_desc": data.get("proc_desc", None)}
        except Exception as e:
            logger.warning(f"筆記讀取失敗 {legacy}: {e}")

    return {"notes": [], "proc_desc": None}


@router.get("/proc_desc_global")
async def load_global_desc(session_id: str = Query(...)):
    """載入全域資料說明"""
    path = _global_desc_path(session_id)
    if not path.exists():
        return {"value": ""}
    return {"value": path.read_text(encoding="utf-8")}


class ProcDescGlobalRequest(BaseModel):
    value: str = ""

@router.post("/proc_desc_global")
async def save_global_desc(session_id: str = Query(...), req: ProcDescGlobalRequest = None):
    """儲存全域資料說明"""
    path = _global_desc_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((req.value if req else ""), encoding="utf-8")
    return {"ok": True}


@router.post("/notes")
async def save_notes(req: NotebookSaveRequest):
    """儲存筆記：每筆 note 存成獨立 JSON。支援 dataset_path（新）或 file_name（舊）。"""
    if req.dataset_path:
        ndir = _dataset_notes_dir(req.session_id, req.dataset_path)
        if ndir is None:
            raise HTTPException(status_code=400, detail="Invalid dataset_path")
    elif req.file_name:
        ndir = _notes_dir(req.session_id, req.file_name)
    else:
        raise HTTPException(status_code=400, detail="需提供 dataset_path 或 file_name")
    try:
        ndir.mkdir(parents=True, exist_ok=True)

        # 刪除舊的 note_*.json（完整覆寫）
        for old in ndir.glob("note_*.json"):
            old.unlink()

        # 逐筆儲存
        for i, note in enumerate(req.notes):
            note_path = ndir / f"note_{i:04d}.json"
            note_path.write_text(
                json.dumps(note.dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        # proc_desc 存入目錄內 _proc_desc.txt
        proc_path = ndir / "_proc_desc.txt"
        if req.proc_desc is not None:
            proc_path.write_text(req.proc_desc, encoding="utf-8")

        # 若舊格式 .json 存在則自動遷移（刪除，僅限 file_name 路徑）
        if req.file_name:
            stem = _stem_from_name(req.file_name)
            legacy = _legacy_notes_path(req.session_id, stem)
            if legacy.exists():
                legacy.unlink()
                logger.info(f"已遷移舊格式筆記：{legacy} → {ndir}/")

        return {"ok": True, "path": str(ndir), "count": len(req.notes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"筆記儲存失敗: {e}")


# ===== Stats Term Translation =====

def _translate_stats_terms(text: str) -> str:
    """將筆記中的統計術語替換成工程師語言，避免 LLM 直接複述統計術語"""
    import re
    replacements = [
        # T² 相關
        (r"T²\s*[值=]\s*([\d,\.]+)", r"製程偏離指數 \1"),
        (r"T²", "製程偏離程度"),
        # UCL / LCL
        (r"UCL99\s*[=為]\s*([\d\.]+)", r"正常上限（99%）= \1"),
        (r"UCL95\s*[=為]\s*([\d\.]+)", r"正常上限（95%）= \1"),
        (r"超出\s*UCL99", "明顯超出正常範圍"),
        (r"超出\s*UCL95", "超出一般正常範圍"),
        (r"UCL99", "正常上限"),
        (r"UCL95", "正常上限（寬鬆）"),
        (r"UCL", "正常上限"),
        # p 值
        (r"p\s*[<＜]\s*0\.001", "幾乎確定相關（p<0.001）"),
        (r"p\s*[<＜]\s*0\.05", "有顯著相關（p<0.05）"),
        (r"p\s*值", "相關顯著性"),
        # PCA
        (r"PCA\s*分析", "多變量分析"),
        (r"PCA", "多變量分析"),
        # 貢獻比例
        (r"貢獻比例\s*([\d\.]+)%", r"影響佔比 \1%"),
        (r"貢獻度\s*([\d\.]+)%", r"影響佔比 \1%"),
        # 顯著差異
        (r"顯著差異", "明顯差異"),
        (r"具顯著", "明顯"),
        # 主成分
        (r"主成分\s*\d+\s*個", lambda m: m.group(0).replace("主成分", "分析維度")),
    ]
    for pattern, repl in replacements:
        if callable(repl):
            text = re.sub(pattern, repl, text)
        else:
            text = re.sub(pattern, repl, text)
    return text


# ===== Token Estimation =====

def _estimate_tokens(messages: List[Dict[str, Any]]) -> dict:
    """粗估 token 數（中文每字≈1 token，ASCII 每4字≈1 token，圖片≈512 token/張）"""
    total_text_tokens = 0
    total_image_tokens = 0
    breakdown = []

    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        msg_text_tokens = 0
        msg_images = 0

        if isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    txt = part.get("text", "")
                    msg_text_tokens += _count_text_tokens(txt)
                elif part.get("type") == "image_url":
                    msg_images += 1
        else:
            msg_text_tokens += _count_text_tokens(str(content))

        img_tokens = msg_images * 512
        total_text_tokens += msg_text_tokens
        total_image_tokens += img_tokens
        breakdown.append(
            f"  [{role}] 文字≈{msg_text_tokens:,} tok"
            + (f" + {msg_images}張圖≈{img_tokens:,} tok" if msg_images else "")
        )

    total = total_text_tokens + total_image_tokens
    return {"total": total, "text": total_text_tokens, "image": total_image_tokens, "breakdown": breakdown}


def _count_text_tokens(text: str) -> int:
    tokens = 0
    ascii_chars = 0
    for ch in text:
        if ord(ch) > 127:  # CJK / 非 ASCII
            tokens += ascii_chars // 4
            ascii_chars = 0
            tokens += 1
        else:
            ascii_chars += 1
    tokens += ascii_chars // 4
    return tokens


# ===== Streaming Helper =====

async def _stream_llm(messages: List[Dict[str, Any]]):
    """向地端 LLM 發送請求，yield SSE 格式字串"""
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    # Token 估算 log
    est = _estimate_tokens(messages)
    print(
        f"\n{'='*52}\n"
        f"  📤 送出 {len(messages)} 則訊息  |  預估 token：{est['total']:,}\n"
        f"  文字 ≈ {est['text']:,}  |  圖片 ≈ {est['image']:,} ({est['image']//512} 張)\n"
        + "\n".join(est["breakdown"]) +
        f"\n{'='*52}",
        flush=True
    )

    # Log message structure (without actual image data)
    structure = []
    for m in messages:
        if isinstance(m.get("content"), list):
            parts = [p.get("type") for p in m["content"]]
            structure.append(f"{m['role']}:[{','.join(parts)}]")
        else:
            structure.append(f"{m['role']}:text({len(str(m.get('content','')))})")
    logger.info(f"_stream_llm payload structure: {' | '.join(structure)}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", config.LLM_API_URL, json=payload) as resp:
                if resp.status_code != 200:
                    body = ""
                    async for chunk in resp.aiter_text():
                        body += chunk
                        if len(body) > 500:
                            break
                    err = json.dumps(
                        {"error": f"LLM 回應失敗 ({resp.status_code}): {body[:300]}"},
                        ensure_ascii=False,
                    )
                    yield f"event: error\ndata: {err}\n\n"
                    return

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        yield "event: done\ndata: {}\n\n"
                        return
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield f"event: text\ndata: {json.dumps({'content': text}, ensure_ascii=False)}\n\n"
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    except httpx.ConnectError:
        err = json.dumps({"error": "無法連線到地端 LLM，請確認服務是否啟動"}, ensure_ascii=False)
        yield f"event: error\ndata: {err}\n\n"
    except Exception as e:
        err = json.dumps({"error": f"串流錯誤: {str(e)}"}, ensure_ascii=False)
        yield f"event: error\ndata: {err}\n\n"

    yield "event: done\ndata: {}\n\n"


# ===== Route =====

@router.post("/chat")
async def notebook_chat(request: NotebookChatRequest):
    """
    分析筆記本聊天 — 串流回應
    將所有筆記注入 system prompt，讓 LLM 根據筆記內容回答問題
    """

    # 1. 組建筆記上下文（含圖片編號對應）
    note_images: List[str] = []
    notes_text_parts: List[str] = []
    img_idx = 1
    for n in request.notes:
        imgs = n.imageData or []
        if imgs:
            if len(imgs) == 1:
                label = f"（附圖 {img_idx}）"
            else:
                label = f"（附圖 {img_idx}–{img_idx + len(imgs) - 1}）"
            note_images.extend(imgs)
            img_idx += len(imgs)
        else:
            label = ""
        # 筆記文字一律加入 context（無論有無圖片）
        notes_text_parts.append(f"【{n.tool}】{label}\n{_translate_stats_terms(n.text)}")

    proc_block = ""
    if request.process_context and request.process_context.strip():
        proc_block += f"\n\n【製程背景說明】\n{request.process_context.strip()}\n請優先依據此製程背景解讀數據，使用正確的製程術語與站別名稱。"
    if request.column_names:
        cols_str = "、".join(request.column_names)
        proc_block += f"\n\n【資料集欄位（共 {len(request.column_names)} 個）】\n{cols_str}\n當使用者提到參數名稱時，請對應到上述欄位。"

    if request.column_stats:
        # 只保留筆記中有提到的欄位統計，避免 LLM 自行分析無關欄位
        notes_combined = " ".join(n.text for n in request.notes)
        relevant_stats = {
            col: s for col, s in request.column_stats.items()
            if col in notes_combined
        }
        if relevant_stats:
            stat_lines = []
            for col, s in relevant_stats.items():
                parts = []
                if s.get("mean") is not None:
                    parts.append(f"均值={s['mean']}")
                if s.get("std") is not None:
                    parts.append(f"標準差={s['std']}")
                if s.get("min") is not None:
                    parts.append(f"最小={s['min']}")
                if s.get("max") is not None:
                    parts.append(f"最大={s['max']}")
                if s.get("median") is not None:
                    parts.append(f"中位數={s['median']}")
                if s.get("count") is not None:
                    parts.append(f"筆數={s['count']}")
                stat_lines.append(f"  {col}: {', '.join(parts)}")
            proc_block += f"\n\n【筆記中提及欄位的統計（用於量化比較，勿主動分析其他欄位）】\n" + "\n".join(stat_lines)

    # ── 圖片優先模式：使用者有附截圖 → 忽略筆記上下文，只看圖 + 對話 + 打字 ──
    image_only_mode = bool(request.images)

    if image_only_mode:
        # 簡化 system prompt，不帶任何筆記內容
        _proc_hint = f"（製程背景：{request.process_context.strip()[:120]}）" if request.process_context and request.process_context.strip() else ""
        context_block = (
            f"你是一位分析助理，擅長解讀工程截圖與數據圖表。{_proc_hint}"
            "請仔細觀察附上的圖片，結合對話歷史與使用者的問題，給出清楚、具體的分析。"
            "條列式回答，禁止加收尾語，回答使用繁體中文。"
        )
        note_images = []  # 不帶筆記截圖，僅分析使用者附上的圖
    elif request.notes:
        notes_text = "\n\n".join(notes_text_parts)
        context_block = f"""以下是使用者在分析「{request.file_name}」時所記錄的分析筆記：

{notes_text}
{proc_block}
---
你是一位資深製程工程師，看得懂數據分析的結果。{f"依據資料說明，你熟悉此製程的背景與術語。" if request.process_context and request.process_context.strip() else ""}上方的筆記是這份資料的診斷發現。

你的任務是幫工程師看懂這些發現代表什麼、可以去追查什麼。數據能告訴你哪個參數異常，但「為什麼異常、去哪裡查、可能是什麼機構問題」是你的製程知識的責任。請主動運用你對製程的理解，給出具體可追查的方向，不要等工程師一直追問。

【回答格式規則（必須遵守）】
- 使用條列式（bullet point）或編號清單，不要寫長段落。
- 每個要點一行，清楚、簡短。需要補充說明時，用次層縮排（  →）。
- 有多個面向時，用粗體標題（**標題**）分組，例如 **配方面**、**機台面**、**建議行動**。
- 禁止在結尾加「希望以上分析...」「如有需要...」「請進一步...」等收尾語，直接停在最後一個實質要點。

其他注意事項：
- 避免統計術語（T²、UCL、p 值、PCA 等），改用工程師聽得懂的語言。
- 數據裡看到的發現 + 你的製程知識 = 可行動的建議。清楚標明哪些是數據支持、哪些是你的推斷。
- 欄位統計只用來輔助說明筆記中已提到的參數，不要自行延伸分析筆記沒有提及的欄位。
- 參考對話歷史維持上下文連貫。
- 回答使用繁體中文。"""
    else:
        context_block = f"""使用者正在分析檔案「{request.file_name}」，目前尚未記錄任何筆記。
{proc_block}
你是一位資深製程工程師，請用現場工程師看得懂的語言回答問題。{f"依據資料說明，你熟悉此製程的背景與術語。" if request.process_context and request.process_context.strip() else ""}
使用條列式或編號清單回答，不寫長段落；有多個面向時用粗體標題分組；禁止加收尾語。避免統計術語，參考對話歷史維持連貫，回答使用繁體中文。"""

    # 2. 組建 messages
    messages = [{"role": "system", "content": context_block}]

    # 加入對話歷史（最多保留最近 20 則，並過濾空 content、確保角色交替）
    recent_history = request.history[-20:] if len(request.history) > 20 else request.history
    for msg in recent_history:
        content = (msg.get("content") or "").strip()
        if not content:
            continue  # 跳過空訊息
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        # 確保角色不連續重複（排除 system 後的最後一條）
        if messages and messages[-1]["role"] == role:
            continue
        messages.append({"role": role, "content": content})

    # 加入本次使用者訊息（支援多模態圖片）
    user_msg = (request.message or "").strip() or "(請分析附上的圖片)"
    if request.images:
        for i, img in enumerate(request.images):
            logger.info(f"  image[{i}]: len={len(img)}, prefix={img[:60]}")
    logger.info(f"notebook_chat: images={len(request.images)}, msg_len={len(user_msg)}, history={len(request.history)}, last_msg_role={messages[-1]['role'] if messages else 'none'}")
    if not messages or messages[-1]["role"] != "user":
        history_rounds = len(request.history) // 2  # 每輪 = user + assistant
        include_images = history_rounds <= 3         # 前 3 輪帶圖，之後純文字

        if image_only_mode:
            # 圖片模式：不帶筆記摘要，只看圖 + 對話 + 打字
            summary_block = ""
            all_images = request.images
        else:
            # 筆記文字摘要（始終附在 user message，讓 LLM 每輪都能對照）
            notes_summary = "\n\n".join(
                f"【{n.tool}】{_translate_stats_terms(n.text)}" for n in request.notes if n.text.strip()
            )
            format_reminder = "（請用條列式回答，禁用 T²/UCL/PCA/p值等統計術語，禁止加收尾語）"
            summary_block = f"\n\n---\n【筆記摘要參考】\n{notes_summary}\n{format_reminder}" if notes_summary else f"\n{format_reminder}"
            # 合併筆記截圖 + 使用者上傳的圖（history > 3 輪後不帶圖）
            all_images = (note_images + request.images) if include_images else request.images
        try:
            import json as _j, os as _os
            _sp = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "settings.json")
            _lim = _j.load(open(_sp, encoding="utf-8")).get("advanced", {}).get("llm_image_limit", 0) if _os.path.exists(_sp) else 0
            if _lim and int(_lim) > 0:
                all_images = all_images[:int(_lim)]
        except Exception:
            pass

        if all_images:
            content_parts: List[Any] = []
            for data_url in all_images:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "high"}
                })
            img_prompt = "請仔細觀察圖片，然後回答：" if image_only_mode else "請先仔細觀察並描述圖片中所有可見內容，然後回答："
            full_text = f"{img_prompt}{user_msg}{summary_block}"
            content_parts.append({"type": "text", "text": full_text})
            messages.append({"role": "user", "content": content_parts})
        else:
            messages.append({"role": "user", "content": user_msg + summary_block})

    return StreamingResponse(
        _stream_llm(messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ===== Mind Map Endpoint =====

class MindMapRequest(BaseModel):
    text: str
    is_global: bool = False
    viz_type: str = "mindmap"   # mindmap | timeline | table | kpi


_VIZ_PROMPTS = {
    "mindmap_single": """請將以下分析文字整理成心智圖 Markdown 格式。
規則：# 根節點（8字內）；3～5 個 ## 分類（6字內）；每類 2～4 條 - 要點（20字內）。
只輸出 Markdown，不加其他文字。\n\n分析內容：\n{text}""",

    "mindmap_global": """以下是多輪對話的 AI 回應（--- 分隔）。跨輪次彙整全域心智圖。
規則：# 根節點（8字內）；4～6 個 ## 分類；每類 3～5 條 - 要點（20字內），去除重複。
只輸出 Markdown，不加其他文字。\n\n內容：\n{text}""",

    "timeline": """請將以下分析文字整理成時間軸 JSON。
格式（嚴格遵守，只輸出 JSON 陣列，不加其他文字）：
[
  {{"date": "2025/01/16", "title": "事件標題（10字內）", "desc": "說明（25字內）", "type": "anomaly"}},
  ...
]
type 只能是：anomaly（異常）| action（行動）| finding（發現）| normal（正常）
若無明確日期，用「—」。最多 10 筆。\n\n分析內容：\n{text}""",

    "table": """請將以下分析文字整理成 Markdown 表格摘要。
規則：
- 第一行為表格標題（用 **粗體** 寫一行說明）
- 表格欄位依內容自訂（如：面向 | 發現 | 建議行動）
- 最多 8 列，每格 25 字內
- 只輸出標題行 + Markdown 表格，不加其他文字\n\n分析內容：\n{text}""",

    "kpi": """請將以下分析文字整理成 KPI 卡片 JSON。
格式（嚴格遵守，只輸出 JSON 陣列，不加其他文字）：
[
  {{"label": "指標名稱（8字內）", "value": "數值或結論（10字內）", "sub": "補充說明（20字內）", "color": "red"}},
  ...
]
color 只能是：red（問題/警告）| green（正常/好）| blue（資訊）| orange（需注意）
最多 8 張卡片。\n\n分析內容：\n{text}""",
}


@router.post("/mindmap")
async def notebook_mindmap(request: MindMapRequest):
    """
    多種視覺化摘要生成：mindmap / timeline / table / kpi
    回傳 { result: "...", viz_type: "..." }
    """
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="text 不可為空")

    vtype = request.viz_type or "mindmap"
    if vtype == "mindmap":
        key = "mindmap_global" if request.is_global else "mindmap_single"
    else:
        key = vtype

    if key not in _VIZ_PROMPTS:
        raise HTTPException(status_code=400, detail=f"不支援的 viz_type: {vtype}")

    prompt = _VIZ_PROMPTS[key].format(text=request.text.strip())
    is_json_type = vtype in ("timeline", "kpi")

    messages = [
        {"role": "system", "content": "你是資訊整理助手，只輸出指定格式，不輸出任何其他文字。"},
        {"role": "user", "content": prompt},
    ]
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 900 if request.is_global else 600,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(config.LLM_API_URL, json=payload)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"LLM 回應失敗 ({resp.status_code})")
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            # 移除 code block 包裝
            raw = re.sub(r"^```(?:json|markdown)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw).strip()
            # 驗證 JSON 類型
            if is_json_type:
                try:
                    json.loads(raw)   # validate
                except json.JSONDecodeError:
                    raise HTTPException(status_code=500, detail="LLM 回傳格式錯誤（非 JSON）")
            return {"result": raw, "viz_type": vtype}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM 請求逾時")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"viz error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
