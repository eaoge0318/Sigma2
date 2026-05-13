"""
資料庫查詢 Router
支援 MS SQL Server 連線、資料表瀏覽、SQL 預覽、匯出 CSV 至 session
連線/樣板/歷史紀錄均為 per-session 隔離
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import asyncio
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime

import config

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== Session 路徑輔助 =====

def _safe_sid(session_id: str) -> str:
    return "".join(c for c in (session_id or "default") if c.isalnum() or c in ("-", "_")) or "default"

def _session_dir(session_id: str) -> Path:
    d = Path(config.BASE_STORAGE_DIR) / _safe_sid(session_id) / "db"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _conn_file(session_id: str) -> Path:
    return _session_dir(session_id) / "connections.json"

def _tpl_file(session_id: str) -> Path:
    return _session_dir(session_id) / "templates.json"

def _hist_file(session_id: str) -> Path:
    return _session_dir(session_id) / "history.json"

def _mapping_file(session_id: str, conn_id: str) -> Path:
    safe = "".join(c for c in (conn_id or "") if c.isalnum() or c in ("-", "_"))
    return _session_dir(session_id) / f"mappings_{safe}.json"


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ===== 資料模型 =====

class ConnectionCreate(BaseModel):
    id: Optional[str] = None
    name: str
    server: str
    database: str
    auth_type: str = "windows"
    username: Optional[str] = ""
    password: Optional[str] = ""
    driver: Optional[str] = ""


class QueryRequest(BaseModel):
    connection_id: str
    sql: str
    session_id: Optional[str] = "default"
    limit: Optional[int] = 100


class ExportRequest(BaseModel):
    connection_id: str
    sql: str
    filename: Optional[str] = ""
    session_id: Optional[str] = "default"


class TemplateSave(BaseModel):
    id: Optional[str] = None
    name: str
    sql: str
    connection_id: Optional[str] = ""


class HistoryAdd(BaseModel):
    connection_id: str
    connection_name: str
    sql: str
    row_count: int = 0
    duration_ms: float = 0


class MappingCreate(BaseModel):
    connection_id: str
    table: str
    schema: str = "dbo"
    def_table: str
    def_schema: str = "dbo"
    display_col: Optional[str] = None   # 使用者選擇的 DEF 顯示欄位
    session_id: Optional[str] = "default"


# ===== 輔助函式 =====

def _get_best_driver() -> str:
    try:
        import pyodbc
        available = [d for d in pyodbc.drivers() if "SQL Server" in d]
        preferred = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "SQL Server Native Client 11.0",
            "SQL Server",
        ]
        for p in preferred:
            if p in available:
                return p
        return available[0] if available else "ODBC Driver 17 for SQL Server"
    except Exception:
        return "ODBC Driver 17 for SQL Server"


def _build_conn_str(conn: dict, driver: str = None) -> str:
    drv = driver or conn.get("driver") or _get_best_driver()

    # ODBC 使用逗號分隔 port（非冒號），並加 tcp: 前綴強制走 TCP/IP
    server = conn["server"].strip()
    if ":" in server and not server.startswith("tcp:"):
        # 10.10.30.10:1433 → tcp:10.10.30.10,1433
        host, port = server.rsplit(":", 1)
        server = f"tcp:{host},{port}"
    elif not server.startswith("tcp:"):
        server = f"tcp:{server}"

    s = f"DRIVER={{{drv}}};SERVER={server};DATABASE={conn['database']};"
    if conn.get("auth_type") == "sql":
        s += f"UID={conn.get('username','')};PWD={conn.get('password','')};"
    else:
        s += "Trusted_Connection=yes;"
    s += "Connect Timeout=10;"
    return s


# ===== 連線管理 =====

@router.get("/drivers")
async def list_drivers():
    try:
        import pyodbc
        drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
        return {"drivers": drivers, "recommended": _get_best_driver()}
    except Exception as e:
        return {"drivers": [], "recommended": "", "error": str(e)}


@router.get("/connections")
async def get_connections(session_id: str = Query("default")):
    conns = _read_json(_conn_file(session_id), [])
    safe = []
    for c in conns:
        s = dict(c)
        if s.get("password"):
            s["password"] = "••••••"
        safe.append(s)
    return {"connections": safe}


@router.post("/connections")
async def save_connection(req: ConnectionCreate, session_id: str = Query("default")):
    cf = _conn_file(session_id)
    conns = _read_json(cf, [])
    now = datetime.now().isoformat()
    if req.id:
        found = False
        for c in conns:
            if c["id"] == req.id:
                c.update({
                    "name": req.name, "server": req.server,
                    "database": req.database, "auth_type": req.auth_type,
                    "username": req.username or "", "driver": req.driver or "",
                    "updated_at": now,
                })
                if req.password and req.password != "••••••":
                    c["password"] = req.password
                found = True
                break
        if not found:
            raise HTTPException(404, "連線不存在")
    else:
        conns.append({
            "id": str(uuid.uuid4()), "name": req.name,
            "server": req.server, "database": req.database,
            "auth_type": req.auth_type, "username": req.username or "",
            "password": req.password or "", "driver": req.driver or "",
            "created_at": now,
        })
    _write_json(cf, conns)
    return {"ok": True}


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: str, session_id: str = Query("default")):
    cf = _conn_file(session_id)
    conns = _read_json(cf, [])
    conns = [c for c in conns if c["id"] != conn_id]
    _write_json(cf, conns)
    return {"ok": True}


@router.post("/test")
async def test_connection(req: ConnectionCreate, session_id: str = Query("default")):
    def _test():
        import pyodbc
        password = req.password
        if password == "••••••" and req.id:
            for c in _read_json(_conn_file(session_id), []):
                if c["id"] == req.id:
                    password = c.get("password", "")
                    break
        tmp = req.dict()
        tmp["password"] = password
        conn_str = _build_conn_str(tmp, req.driver or None)
        with pyodbc.connect(conn_str, timeout=10) as con:
            cur = con.cursor()
            cur.execute("SELECT @@VERSION")
            row = cur.fetchone()
            return row[0].split("\n")[0].strip() if row else "連線成功"

    try:
        version = await asyncio.to_thread(_test)
        return {"ok": True, "version": version}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ===== 資料表瀏覽 =====

@router.post("/tables")
async def list_tables(body: dict):
    session_id = body.get("session_id", "default")
    conn_id = body.get("connection_id")
    conn = next((c for c in _read_json(_conn_file(session_id), []) if c["id"] == conn_id), None)
    if not conn:
        raise HTTPException(404, "連線不存在")

    def _list():
        import pyodbc
        conn_str = _build_conn_str(conn)
        with pyodbc.connect(conn_str, timeout=10) as con:
            cur = con.cursor()
            tables = [{"schema": r.table_schem, "name": r.table_name, "full": f"{r.table_schem}.{r.table_name}"}
                      for r in cur.tables(tableType="TABLE")]
            views  = [{"schema": r.table_schem, "name": r.table_name, "full": f"{r.table_schem}.{r.table_name}"}
                      for r in cur.tables(tableType="VIEW")]
            return tables, views

    try:
        tables, views = await asyncio.to_thread(_list)
        return {"tables": tables, "views": views}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/columns")
async def list_columns(body: dict):
    session_id = body.get("session_id", "default")
    conn_id = body.get("connection_id")
    table_schema = body.get("schema", "dbo")
    table_name = body.get("table")
    conn = next((c for c in _read_json(_conn_file(session_id), []) if c["id"] == conn_id), None)
    if not conn:
        raise HTTPException(404, "連線不存在")

    def _cols():
        import pyodbc
        conn_str = _build_conn_str(conn)
        with pyodbc.connect(conn_str, timeout=10) as con:
            cur = con.cursor()
            return [{"name": r.column_name, "type": r.type_name, "nullable": r.nullable == 1}
                    for r in cur.columns(table=table_name, schema=table_schema)]

    try:
        return {"columns": await asyncio.to_thread(_cols)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ===== 查詢 =====

@router.post("/preview")
async def preview_query(req: QueryRequest):
    session_id = req.session_id or "default"
    conn = next((c for c in _read_json(_conn_file(session_id), []) if c["id"] == req.connection_id), None)
    if not conn:
        raise HTTPException(404, "連線不存在")

    import time

    def _run():
        conn_str = _build_conn_str(conn)
        t0 = time.time()
        import pyodbc, pandas as pd
        with pyodbc.connect(conn_str, timeout=30) as con:
            df = pd.read_sql(req.sql, con)
        if req.limit and len(df) > req.limit:
            df = df.head(req.limit)
        elapsed = round((time.time() - t0) * 1000)
        # astype(object) 確保 NaN/Inf 都能被替換成 None（原生 float NaN 無法 JSON 序列化）
        safe = df.astype(object).where(df.notna(), None)
        import math
        def _safe_val(v):
            if v is None:
                return None
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            if isinstance(v, bytes):
                # Try common encodings: UTF-8 → Big5 → Latin-1 (lossless fallback)
                for enc in ('utf-8', 'big5', 'gbk', 'latin-1'):
                    try:
                        return v.decode(enc)
                    except (UnicodeDecodeError, LookupError):
                        continue
                return v.hex()  # last resort: hex string
            return v
        rows = [
            [_safe_val(v) for v in row]
            for row in safe.values.tolist()
        ]
        return list(df.columns), rows, elapsed, len(df)

    try:
        cols, rows, elapsed, total = await asyncio.to_thread(_run)
        return {"columns": cols, "rows": rows, "row_count": total, "duration_ms": elapsed}
    except Exception as e:
        err_msg = str(e)
        # pandas DatabaseError includes the full SQL — extract just the DB error
        import re as _re
        # Pattern: "Execution failed on sql 'SELECT ...': (pyodbc.Error) ('code', 'message')"
        m = _re.search(r"\(pyodbc\.\w+\)\s*\(([^)]+)\)", err_msg)
        if m:
            err_msg = m.group(1).strip().strip("'\"")
        elif len(err_msg) > 500:
            err_msg = err_msg[:500] + "…"
        logger.error(f"[DB Preview] SQL 執行失敗: {err_msg}")
        raise HTTPException(500, err_msg)


@router.post("/export")
async def export_query(req: ExportRequest):
    import time
    session_id = req.session_id or "default"
    conn = next((c for c in _read_json(_conn_file(session_id), []) if c["id"] == req.connection_id), None)
    if not conn:
        raise HTTPException(404, "連線不存在")

    def _run():
        conn_str = _build_conn_str(conn)
        t0 = time.time()
        import pyodbc, pandas as pd
        with pyodbc.connect(conn_str, timeout=60) as con:
            df = pd.read_sql(req.sql, con)
        return df, round((time.time() - t0) * 1000)

    try:
        df, elapsed = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, str(e))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = (req.filename or "").strip() or f"db_export_{ts}.csv"
    if not out_name.lower().endswith(".csv"):
        out_name += ".csv"

    upload_dir = Path(config.BASE_STORAGE_DIR) / _safe_sid(session_id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    (upload_dir / out_name).write_bytes(csv_bytes)
    logger.info(f"[DB Export] {len(df)} rows → {upload_dir / out_name}")

    from urllib.parse import quote
    encoded_name = quote(out_name, safe='')
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "X-Row-Count": str(len(df)),
            "X-Duration-Ms": str(elapsed),
            "X-Saved-Filename": encoded_name,
        },
    )


# ===== 樣板管理 =====

@router.get("/templates")
async def get_templates(session_id: str = Query("default")):
    return {"templates": _read_json(_tpl_file(session_id), [])}


@router.post("/templates")
async def save_template(req: TemplateSave, session_id: str = Query("default")):
    tf = _tpl_file(session_id)
    tpls = _read_json(tf, [])
    now = datetime.now().isoformat()
    if req.id:
        for t in tpls:
            if t["id"] == req.id:
                t.update({"name": req.name, "sql": req.sql,
                           "connection_id": req.connection_id, "updated_at": now})
                break
        else:
            raise HTTPException(404, "樣板不存在")
    else:
        tpls.insert(0, {"id": str(uuid.uuid4()), "name": req.name,
                        "sql": req.sql, "connection_id": req.connection_id or "",
                        "created_at": now})
    _write_json(tf, tpls)
    return {"ok": True}


@router.delete("/templates/{tpl_id}")
async def delete_template(tpl_id: str, session_id: str = Query("default")):
    tf = _tpl_file(session_id)
    tpls = [t for t in _read_json(tf, []) if t["id"] != tpl_id]
    _write_json(tf, tpls)
    return {"ok": True}


# ===== 欄位對應（DEF Table 自動偵測）=====

@router.post("/field-mapping")
async def get_field_mapping(body: dict):
    """
    取得欄位對應。
    - 若傳入 def_table：直接使用指定的 DEF 表（來自使用者配對設定）
    - 若未傳入：自動偵測 {TABLE}DEF
    DEF 表結構：DEFTABLE, DEFFIELD (實際欄位), VARIABLENAME (顯示名稱)
    """
    session_id = body.get("session_id", "default")
    conn_id = body.get("connection_id")
    table_name = body.get("table")           # e.g. METROLOGY
    table_schema = body.get("schema", "dbo")
    explicit_def_table = body.get("def_table")    # 使用者指定的 DEF 表
    explicit_def_schema = body.get("def_schema", table_schema)
    explicit_display_col = body.get("display_col")  # 使用者指定的顯示欄位

    conn = next((c for c in _read_json(_conn_file(session_id), []) if c["id"] == conn_id), None)
    if not conn:
        raise HTTPException(404, "連線不存在")

    def _detect():
        import pyodbc
        import pandas as pd
        conn_str = _build_conn_str(conn)
        with pyodbc.connect(conn_str, timeout=15) as con:
            cur = con.cursor()
            if explicit_def_table:
                # 使用者已配對，直接使用指定的 DEF 表
                def_table = explicit_def_table
                def_schema = explicit_def_schema
            else:
                # 自動偵測 {TABLE}DEF
                def_table = table_name + "DEF"
                def_schema = table_schema
                exists = any(
                    r.table_name.upper() == def_table.upper() and r.table_schem.upper() == def_schema.upper()
                    for r in cur.tables(table=def_table, schema=def_schema)
                )
                if not exists:
                    return None, None, None, None

            # 取得 DEF 表的欄位清單
            col_sql = ("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                       "WHERE UPPER(TABLE_SCHEMA) = UPPER(?) AND UPPER(TABLE_NAME) = UPPER(?)")
            def_columns = {r[0].upper() for r in cur.execute(col_sql, def_schema, def_table).fetchall()}

            # 決定顯示名稱欄位：優先使用使用者明確指定的，否則自動偵測
            if explicit_display_col and explicit_display_col.upper() in def_columns:
                display_col = explicit_display_col.upper()
            else:
                _DISPLAY_CANDIDATES = ["VARIABLENAME", "AVMNAME", "VARIABLE_NAME",
                                       "DISPLAY_NAME", "DESCRIPTION", "NAME"]
                display_col = None
                for candidate in _DISPLAY_CANDIDATES:
                    if candidate in def_columns:
                        display_col = candidate
                        break

            if not display_col:
                return None, None, None, None

            return_cols = sorted(def_columns - {"DEFTABLE", "DEFFIELD"})

            sql = (f"SELECT DEFFIELD, [{display_col}] FROM [{def_schema}].[{def_table}]"
                   f" WHERE UPPER(DEFTABLE) = UPPER(?)")
            df = pd.read_sql(sql, con, params=[table_name])
            mapping = {row["DEFFIELD"]: row[display_col] for _, row in df.iterrows()}
            return def_table, def_schema, mapping, return_cols

    try:
        def_table, def_schema, mapping, def_cols = await asyncio.to_thread(_detect)
        if mapping is None:
            return {"found": False}
        return {"found": True, "def_table": def_table, "mapping": mapping, "def_cols": def_cols}
    except Exception as e:
        return {"found": False, "error": str(e)}


# ===== 配對管理（Table ↔ DEF Table，per session + connection）=====

@router.get("/mappings")
async def get_mappings(session_id: str = Query("default"), connection_id: str = Query(...)):
    return {"mappings": _read_json(_mapping_file(session_id, connection_id), [])}


@router.post("/mappings")
async def save_mapping(req: MappingCreate):
    sid = req.session_id or "default"
    mf = _mapping_file(sid, req.connection_id)
    mappings = _read_json(mf, [])
    # 若同一資料表已有配對，更新之
    for m in mappings:
        if m["table"].upper() == req.table.upper() and m["schema"].upper() == req.schema.upper():
            m["def_table"] = req.def_table
            m["def_schema"] = req.def_schema
            m["display_col"] = req.display_col
            _write_json(mf, mappings)
            return {"ok": True, "updated": True}
    mappings.append({
        "id": str(uuid.uuid4()),
        "table": req.table, "schema": req.schema,
        "def_table": req.def_table, "def_schema": req.def_schema,
        "display_col": req.display_col,
    })
    _write_json(mf, mappings)
    return {"ok": True, "updated": False}


@router.post("/mappings/reorder")
async def reorder_mappings(body: dict, session_id: str = Query("default"), connection_id: str = Query(...)):
    """依照前端傳入的 id 順序重新排列配對清單"""
    ids: list = body.get("ids", [])
    mf = _mapping_file(session_id, connection_id)
    mappings = _read_json(mf, [])
    id_map = {m["id"]: m for m in mappings}
    reordered = [id_map[i] for i in ids if i in id_map]
    # 補上不在 ids 裡的（安全起見）
    existing_ids = {m["id"] for m in reordered}
    reordered += [m for m in mappings if m["id"] not in existing_ids]
    _write_json(mf, reordered)
    return {"ok": True}


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(mapping_id: str, session_id: str = Query("default"), connection_id: str = Query(...)):
    mf = _mapping_file(session_id, connection_id)
    mappings = [m for m in _read_json(mf, []) if m["id"] != mapping_id]
    _write_json(mf, mappings)
    return {"ok": True}


# ===== 查詢歷史 =====

@router.get("/history")
async def get_history(session_id: str = Query("default")):
    return {"history": _read_json(_hist_file(session_id), [])[:30]}


@router.delete("/history/{hist_id}")
async def delete_history(hist_id: str, session_id: str = Query("default")):
    hf = _hist_file(session_id)
    hist = [h for h in _read_json(hf, []) if h["id"] != hist_id]
    _write_json(hf, hist)
    return {"ok": True}


@router.post("/history")
async def add_history(req: HistoryAdd, session_id: str = Query("default")):
    hf = _hist_file(session_id)
    hist = _read_json(hf, [])
    hist.insert(0, {
        "id": str(uuid.uuid4()), "connection_id": req.connection_id,
        "connection_name": req.connection_name, "sql": req.sql,
        "row_count": req.row_count, "duration_ms": req.duration_ms,
        "executed_at": datetime.now().isoformat(),
    })
    _write_json(hf, hist[:30])
    return {"ok": True}
