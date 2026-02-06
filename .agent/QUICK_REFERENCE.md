# Sigma2 新工具使用快速參考

## 📝 日誌系統

```python
from backend.utils import get_logger

logger = get_logger(__name__)

# 基本使用
logger.debug("除錯訊息")
logger.info("一般資訊")
logger.warning("警告訊息")
logger.error("錯誤訊息")
logger.critical("嚴重錯誤")

# 包含異常資訊
try:
    risky_operation()
except Exception as e:
    logger.error("操作失敗", exc_info=True)
```

## 🚨 異常處理

```python
from backend.utils.exceptions import (
    ValidationError,
    FileNotFoundError,
    ModelTrainingError
)

# 拋出驗證錯誤
if not valid:
    raise ValidationError(
        "參數驗證失敗",
        details={"field": "session_id", "value": session_id}
    )

# 拋出檔案錯誤
if not os.path.exists(path):
    raise FileNotFoundError(path)

# 拋出訓練錯誤
if training_failed:
    raise ModelTrainingError(
        "訓練失敗",
        details={"epoch": epoch, "error": error_msg}
    )
```

## 🔒 安全性工具

```python
from backend.utils.security import (
    sanitize_session_id,
    sanitize_filename,
    validate_file_path
)

# 清理 Session ID
safe_id = sanitize_session_id(request.session_id)

# 清理檔案名稱
safe_name = sanitize_filename(uploaded_filename)

# 驗證路徑
safe_path = validate_file_path(
    file_path=user_path,
    base_dir="/workspace",
    must_exist=True
)
```

## ✅ 數據驗證

```python
from backend.utils.validators import (
    validate_training_inputs,
    validate_dataframe
)

# 驗證訓練參數
validate_training_inputs(
    data_path="data.csv",
    goal_col="target",
    action_features=["A1", "A2"],
    state_features=["S1", "S2"],
    goal_settings={"lsl": 0.0, "usl": 1.0}
)

# 驗證 DataFrame
validate_dataframe(
    df=dataframe,
    min_rows=100,
    required_columns=["target", "feature1"]
)
```

## 📊 API 回應

```python
from backend.models.response_models import (
    create_success_response,
    create_error_response
)

# 成功回應
@app.get("/api/data")
async def get_data():
    return create_success_response(
        data={"result": [1, 2, 3]},
        message="查詢成功"
    )

# 錯誤回應
@app.post("/api/train")
async def train():
    try:
        # ...
    except ValidationError as e:
        return create_error_response(
            error=str(e),
            code="VALIDATION_ERROR",
            details=e.details
        )
```

## ⚙️ 配置系統

```python
from config_new import settings

# 讀取配置
port = settings.API_PORT
log_level = settings.LOG_LEVEL

# 取得演算法配置
iql_config = settings.get_algo_config("IQL")
train_config = settings.get_train_common_config()

# 環境變數 (.env)
# LOG_LEVEL=DEBUG
# API_PORT=8001
```

## 🛡️ 異常中間件

```python
# 在 api_entry.py 中註冊
from backend.middleware.exception_handler import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)

# 之後所有異常會自動處理並返回統一格式
```

## 📚 完整範例

### 服務層整合範例

```python
from backend.utils import get_logger, ValidationError
from backend.utils.security import sanitize_session_id, validate_file_path
from backend.utils.validators import validate_dataframe

logger = get_logger(__name__)

class MyService:
    def process_file(self, filename: str, session_id: str):
        try:
            # 安全性檢查
            safe_id = sanitize_session_id(session_id)
            safe_path = validate_file_path(
                filename, 
                base_dir="/workspace"
            )
            
            # 載入數據
            logger.info(f"載入檔案: {filename}")
            df = pd.read_csv(safe_path)
            
            # 驗證數據
            validate_dataframe(df, min_rows=10)
            
            # 處理數據
            result = self._process(df)
            
            logger.info("處理完成")
            return result
            
        except ValidationError as e:
            logger.error(f"驗證失敗: {e}")
            raise
        except Exception as e:
            logger.error("處理失敗", exc_info=True)
            raise
```

---

查閱完整文檔:
- 整合計劃: `.agent/INTEGRATION_PLAN.md`
- 改善總結: `.agent/IMPROVEMENT_SUMMARY.md`
