# 快速修復: AttributeError 'Depends' object has no attribute 'get_user_path'

## 問題
```
ERROR - backend.routers.dashboard_router - 模型載入失敗: 'Depends' object has no attribute 'get_user_path'
AttributeError: 'Depends' object has no attribute 'get_user_path'
```

## 原因
在 `api_entry.py` 的向後相容路由 `/api/model/load` 中,只傳遞了 `prediction_service`,但新版本的 `load_specific_model` 函數需要三個服務:
- `prediction_service`
- `session_service`
- `file_service`

## 解決方案
修改 `api_entry.py` 第 198-211 行:

```python
@app.post("/api/model/load")
async def model_load_legacy(request: dict):
    """向後相容:載入模型"""
    from backend.routers.dashboard_router import load_specific_model
    from backend.dependencies import get_prediction_service, get_session_service, get_file_service

    model_path = request.get("model_path")
    session_id = request.get("session_id", "default")

    return await load_specific_model(
        model_path=model_path,
        session_id=session_id,
        prediction_service=get_prediction_service(),
        session_service=get_session_service(),  # 新增
        file_service=get_file_service(),        # 新增
    )
```

## 修改檔案
- `api_entry.py`

## 狀態
✅ 已修復 - 2026/02/04 10:59
