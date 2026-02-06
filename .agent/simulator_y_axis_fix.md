# 模擬功能 Y 軸修正 - 2026/02/04

## 問題描述
在執行模擬功能時,圖表的 Y 軸應該要顯示 `job_xxx.json` 檔案中定義的目標標的 (goal 欄位),而不是自動檢測的欄位。

## 解決方案

### 1. 修改 `backend/models/session_models.py`
在 `DashboardSession` 中新增 `current_model_config` 屬性,用於儲存當前載入的模型配置:

```python
@dataclass
class DashboardSession:
    """即時看板 Session"""
    prediction_history: List[Dict[str, Any]] = field(default_factory=list)
    sim_index: int = 0
    sim_df: Any = None
    sim_file_name: Optional[str] = None
    current_model_config: Optional[Dict[str, Any]] = None  # 當前載入的模型配置
```

### 2. 修改 `backend/routers/dashboard_router.py`

#### 2.1 修改 `load_specific_model` 函數
當載入 `job_xxx.json` 模型配置時,將配置儲存到 session 中:

```python
@router.post("/model/load")
async def load_specific_model(
    model_path: str = Body(..., embed=True),
    session_id: str = Body(default="default", embed=True),
    prediction_service: PredictionService = Depends(get_prediction_service),
    session_service: SessionService = Depends(get_session_service),
    file_service: FileService = Depends(get_file_service),
):
    # 載入模型
    agent = prediction_service.get_agent(session_id)
    agent.reload_model(target_bundle_name=model_path)
    
    # 如果是 job_xxx.json 配置檔,讀取並儲存到 session
    if model_path.endswith(".json") and model_path.startswith("job_"):
        import json
        configs_dir = file_service.get_user_path(session_id, "configs")
        config_path = os.path.join(configs_dir, model_path)
        
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                job_config = json.load(f)
            
            # 儲存配置到 session
            session = session_service.get_dashboard_session(session_id)
            session.current_model_config = job_config
```

#### 2.2 修改 `simulator_next` 函數
從 session 中讀取 goal 欄位作為 Y 軸目標標的:

```python
# 從當前載入的模型配置中讀取 goal 欄位作為 Y 軸目標標的
measure_value = None
goal_column = None

# 嘗試從 session 中獲取當前載入的模型配置
if hasattr(session, 'current_model_config') and session.current_model_config:
    goal_column = session.current_model_config.get('goal')
    print(f"[DEBUG] Goal column from model config: {goal_column}")

# 如果有 goal 欄位且該欄位存在於數據中,使用它作為 measure_value
if goal_column and goal_column in row.index:
    measure_value = float(row[goal_column])
    print(f"[DEBUG] Using goal column '{goal_column}' as measure: {measure_value}")
else:
    # 備用方案：自動檢測包含 "std" 或 "measure" 的欄位
    print(f"[WARNING] Goal column not found in session or data, falling back to auto-detection")
    # ... 原有的自動檢測邏輯 ...
```

## 使用流程

1. **載入模型**: 使用 `/api/model/load` API 載入 `job_xxx.json` 配置檔
   - 系統會自動讀取配置中的 `goal` 欄位並儲存到 session

2. **載入模擬檔案**: 使用 `/api/simulator/load_file` API 載入 CSV 檔案

3. **執行模擬**: 使用 `/api/simulator/next` API 執行模擬
   - 系統會自動使用配置中的 `goal` 欄位作為 Y 軸數據
   - 如果找不到 goal 欄位,會回退到自動檢測模式

## 範例

假設 `job_37099f41.json` 中定義:
```json
{
    "goal": "METROLOGY-P21-MO1-SP-2SIGMA",
    ...
}
```

當執行模擬時,系統會自動使用 CSV 檔案中的 `METROLOGY-P21-MO1-SP-2SIGMA` 欄位作為 Y 軸數據。

## 修改檔案清單
- `backend/models/session_models.py`
- `backend/routers/dashboard_router.py`
