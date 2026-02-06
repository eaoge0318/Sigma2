# Sigma2 系統改善 - 逐步整合計劃

## 📋 總覽

本文檔記錄了 Sigma2 系統的三階段改善工作，以及逐步整合新功能的計劃。

**目標**：在確保系統穩定性的前提下，逐步整合新的工具和功能，提升系統的可維護性、安全性和擴展性。

---

## ✅ 已完成的新工具模組

### 1. **統一日誌系統**
- **檔案**: `backend/utils/logger.py`
- **功能**:
  - 自動檔案輪轉 (10MB/5個備份)
  - 支援控制台和檔案雙輸出
  - 環境變數配置 (LOG_LEVEL, LOG_DIR)
  - 自動抑制第三方庫冗長日誌

### 2. **異常處理系統**
- **檔案**: `backend/utils/exceptions.py`
- **功能**:
  - 7 種自定義異常類別 (ValidationError, FileNotFoundError等)
  - 統一錯誤格式 (包含錯誤碼、狀態碼、詳細資訊)
  - 便於追蹤和除錯

### 3. **安全性工具**
- **檔案**: `backend/utils/security.py`  
- **功能**:
  - Session ID 清理與驗證 (防SQL注入)
  - 檔案路徑安全檢查 (防路徑穿越)
  - 檔案名稱清理
  - 欄位名稱驗證

### 4. **數據驗證工具**
- **檔案**: `backend/utils/validators.py`
- **功能**:
  - 訓練參數完整驗證 (validate_training_inputs)
  - 預測參數驗證 (validate_prediction_inputs)
  - DataFrame 質量檢查 (validate_dataframe)
  - 超參數驗證 (validate_hyperparameters)

### 5. **新配置管理系統**
- **檔案**: `config_new.py`
- **功能**:
  - 基於 pydantic-settings 的配置管理
  - 支援環境變數 (.env 檔案)
  - 型別驗證和自動轉換
  - 向後相容舊的 config.py

### 6. **標準 API 回應模型**
- **檔案**: `backend/models/response_models.py`
- **功能**:
  - APIResponse (統一成功回應)
  - ErrorResponse (統一錯誤回應)
  - PaginatedResponse (分頁回應)
  - TaskResponse (異步任務回應)
  - 便捷函數 (create_success_response 等)

### 7. **異常處理中間件**
- **檔案**: `backend/middleware/exception_handler.py`
- **功能**:
  - 自動捕獲所有異常
  - 統一錯誤回應格式
  - 支援 debug 模式 (顯示堆疊追蹤)
  - 註冊函數 (register_exception_handlers)

### 8. **增強數據處理器 (已備份)**
- **備份檔案**: `DataPreprocess_enhanced.py` (建議名稱)
- **功能**:
  - 智能大檔案處理 (分塊讀取)
  - 自動數據清理 (缺失值、重複、異常值)
  - 數據質量驗證
  - 數據摘要生成

---

## 🔄 逐步整合計劃

### **階段 A：核心服務整合 (優先)**

#### A1. 整合日誌系統到核心服務
**目標檔案**: 
- `backend/services/analysis_service.py`
- `backend/services/file_service.py`
- `backend/services/ai_service.py`

**步驟**:
1. 在每個服務檔案開頭添加:
   ```python
   from backend.utils import get_logger
   logger = get_logger(__name__)
   ```

2. 將所有 `print()` 替換為 `logger.info()` / `logger.error()` 等

3. 測試確認日誌正常輸出到檔案和控制台

**預期效果**:
- 所有服務的操作都有日誌記錄
- 便於追蹤問題和除錯

---

#### A2. 整合安全性工具到檔案服務
**目標檔案**: `backend/services/file_service.py`

**步驟**:
1. 導入安全工具:
   ```python
   from backend.utils.security import (
       sanitize_session_id,
       sanitize_filename,
       validate_file_path
   )
   ```

2. 在 `upload_file`, `delete_file`, `view_file` 等方法中添加驗證:
   ```python
   safe_session_id = sanitize_session_id(session_id)
   safe_filename = sanitize_filename(filename)
   safe_path = validate_file_path(file_path, base_dir)
   ```

3. 測試上傳、刪除、查看檔案功能

**預期效果**:
- 防止路徑穿越攻擊
- Session ID 注入防護

---

#### A3. 整合異常處理中間件到 API
**目標檔案**: `api_entry.py`

**步驟**:
1. 在 FastAPI app 初始化後添加:
   ```python
   from backend.middleware.exception_handler import register_exception_handlers
   
   # 在 app = FastAPI(...) 之後
   register_exception_handlers(app)
   ```

2. 測試故意觸發錯誤，檢查回應格式

**預期效果**:
- 所有 API 錯誤都返回統一格式
- 更好的錯誤追蹤

---

### **階段 B：訓練引擎整合 (謹慎)**

#### B1. 整合日誌到訓練引擎
**目標檔案**: 
- `engine_strategy.py`
- `engine_prediction.py`

**步驟**:
1. 在檔案開頭添加 (使用 try-except 確保向後相容):
   ```python
   try:
       from backend.utils import get_logger
       logger = get_logger(__name__)
       USE_NEW_LOGGER = True
   except ImportError:
       import logging
       logger = logging.getLogger(__name__)
       USE_NEW_LOGGER = False
   ```

2. 逐步將 `print()` 替換為 `logger.info()`:
   - 先替換非關鍵路徑的 print
   - 保留訓練迴圈中的 print (避免影響輸出)
   - 測試每次修改

**預期效果**:
- 訓練過程有完整日誌記錄
- 不影響現有功能

---

#### B2. 整合參數驗證到訓練引擎
**目標檔案**: 
- `engine_strategy.py`
- `engine_prediction.py`

**步驟**:
1. 在 `run_parameterized_rl` 開頭添加 (使用 try-except):
   ```python
   try:
       from backend.utils.validators import validate_training_inputs
       validate_training_inputs(
           data_path, goal_col, action_features, 
           state_features, goal_settings
       )
   except ImportError:
       # 使用原有的簡單驗證
       if not data_path or not goal_col:
           raise ValueError("Missing parameters")
   ```

2. 小範圍測試訓練功能

**預期效果**:
- 更嚴格的參數驗證
- 更清晰的錯誤訊息

---

### **階段 C：配置系統遷移 (最後)**

#### C1. 環境變數支援
**步驟**:
1. 建立 `.env.example` 檔案作為範本
2. 文檔化所有支援的環境變數
3. 讓使用者可選擇使用 .env 或保持現狀

#### C2. 逐步遷移到新配置
**步驟**:
1. 保留 `config.py` 不變
2. `config_new.py` 導入 config.py 的值作為預設
3. 逐步引導使用者遷移到新配置

---

## 🧪 測試策略

### **每次整合後必須測試**:
1. ✅ 系統能正常啟動 (`python api_entry.py`)
2. ✅ 現有功能不受影響
3. ✅ 新功能按預期工作
4. ✅ 日誌正確輸出

### **測試檢查清單**:
- [ ] API 服務啟動
- [ ] 檔案上傳/下載
- [ ] 數據分析功能
- [ ] 模型訓練 (IQL)
- [ ] 模型訓練 (XGBoost)
- [ ] AI 報告生成
- [ ] 錯誤處理

---

## 📝 使用示例

### 日誌系統使用
```python
from backend.utils import get_logger

logger = get_logger(__name__)

logger.info("這是資訊訊息")
logger.warning("這是警告訊息")
logger.error("這是錯誤訊息", exc_info=True)  # 包含堆疊追蹤
```

### 異常處理使用
```python
from backend.utils.exceptions import ValidationError, FileNotFoundError

# 拋出自定義異常
if not file_exists:
    raise FileNotFoundError(filepath="/path/to/file")

# 驗證失敗
if invalid_params:
    raise ValidationError(
        "參數驗證失敗",
        details={"field": "session_id", "reason": "不可為空"}
    )
```

### 安全性工具使用
```python
from backend.utils.security import sanitize_session_id, validate_file_path

# 清理 session ID
safe_id = sanitize_session_id(user_input_id)

# 驗證檔案路徑
safe_path = validate_file_path(
    file_path="/uploads/user_file.csv",
    base_dir="/workspace",
    must_exist=True
)
```

### 標準 API 回應
```python
from backend.models.response_models import create_success_response, create_error_response

# 成功回應
return create_success_response(
    data={"result": "success"},
    message="操作完成"
)

# 錯誤回應
return create_error_response(
    error="找不到檔案",
    code="FILE_NOT_FOUND",
    details={"filename": "test.csv"}
)
```

---

## ⚠️ 注意事項

1. **向後相容**: 所有新工具都應該有 try-except 處理，確保即使新模組不可用，系統仍能運作

2. **逐步整合**: 不要一次修改太多檔案，每次只整合一個模組並充分測試

3. **保留原始功能**: 在確認新功能穩定前，保留所有原始的實作方式

4. **文檔記錄**: 每次整合後更新此文檔，記錄修改內容和測試結果

---

## 📊 整合進度追蹤

| 階段 | 任務 | 狀態 | 測試日期 | 備註 |
|------|------|------|----------|------|
| A1 | 日誌系統 - analysis_service | ⏳ 待整合 | - | - |
| A1 | 日誌系統 - file_service | ⏳ 待整合 | - | - |
| A1 | 日誌系統 - ai_service | ⏳ 待整合 | - | - |
| A2 | 安全工具 - file_service | ⏳ 待整合 | - | - |
| A3 | 異常中間件 - api_entry | ⏳ 待整合 | - | - |
| B1 | 日誌系統 - engine_strategy | ⏳ 待整合 | - | 需謹慎測試 |
| B1 | 日誌系統 - engine_prediction | ⏳ 待整合 | - | 需謹慎測試 |
| B2 | 參數驗證 - engine_strategy | ⏳ 待整合 | - | 需謹慎測試 |
| B2 | 參數驗證 - engine_prediction | ⏳ 待整合 | - | 需謹慎測試 |
| C1 | 環境變數支援 | ⏳ 待整合 | - | - |
| C2 | 新配置系統 | ⏳ 待整合 | - | - |

---

## 🔗 相關檔案

- 原始配置: `config.py`
- 新配置系統: `config_new.py`
- 工具模組: `backend/utils/`
- 中間件: `backend/middleware/`
- 回應模型: `backend/models/response_models.py`

---

**最後更新**: 2026-02-03
**版本**: 1.0
**維護者**: Sigma2 Development Team
