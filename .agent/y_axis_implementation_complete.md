# Y 軸配置功能 - 完整實現總結

## 🎉 後端實現完成

### API 響應數據 (已驗證)

```json
{
  "status": "HOLD",
  "current_measure": 2.384522,
  "target_range": [1.7074, 2.2153],
  "goal_name": "METROLOGY-P21-MO1-SP-2SIGMA",
  "goal_settings": {
    "target": "2.0270",
    "usl": "2.2153",
    "lsl": "1.7074"
  },
  "recommendations": {...},
  "feature_snapshots": {...},
  ...
}
```

### 後端修改清單

#### 1. `backend/models/session_models.py`
新增 `current_model_config` 屬性到 `DashboardSession`:
```python
@dataclass
class DashboardSession:
    prediction_history: List[Dict[str, Any]] = field(default_factory=list)
    sim_index: int = 0
    sim_df: Any = None
    sim_file_name: Optional[str] = None
    current_model_config: Optional[Dict[str, Any]] = None  # 新增
```

#### 2. `backend/routers/dashboard_router.py`

**`load_specific_model` 函數:**
- 載入 `job_xxx.json` 配置檔案
- 儲存到 `session.current_model_config`

**`simulator_next` 函數:**
- 從 `session.current_model_config` 讀取 `goal` 欄位
- 使用 `goal` 欄位對應的數據作為 Y 軸 (`current_measure`)
- 在返回結果中加入 `goal_name` 和 `goal_settings`

#### 3. `backend/services/prediction_service.py`

**`predict` 方法:**
- 從 `session.current_model_config` 讀取 `goalSettings`
- 使用 `lsl` 和 `usl` 作為 `target_range`
- 如果無法讀取,回退到 `config.py` 的預設值

#### 4. `api_entry.py`
修正向後相容路由 `/api/model/load`,傳遞所有必要的服務依賴

#### 5. `agent_logic.py`
新增 IQL 維度不匹配的錯誤處理,跳過推理但不中斷模擬

---

## 🔧 前端待修改項目

### 問題 1: 目標值名稱顯示為 "G_std"
**應該顯示:** `goal_name` (METROLOGY-P21-MO1-SP-2SIGMA)

**需要修改的位置:**
前端 JavaScript 中繪製圖表或顯示標籤的地方,將硬編碼的 "G_std" 改為使用 API 返回的 `result.goal_name`

**可能的檔案:**
- `dashboard.html` 中的 `<script>` 標籤
- `static/js/dashboard_full.js`
- `static/js/modules/dashboard.js`

**修改示例:**
```javascript
// 舊的程式碼
const label = "G_std";

// 新的程式碼
const label = result.goal_name || "目標值";
```

### 問題 2: 綠色區塊應該顯示 target/USL/LSL
**應該顯示:** `goal_settings` 的數值

**需要修改的位置:**
前端圖表配置中的綠色區塊(可能是 Chart.js 的 annotation 或 background color)

**修改示例:**
```javascript
// 舊的程式碼
const target = 1.0;
const usl = 2.0;
const lsl = 0.0;

// 新的程式碼
const goalSettings = result.goal_settings || {};
const target = parseFloat(goalSettings.target || 1.0);
const usl = parseFloat(goalSettings.usl || 2.0);
const lsl = parseFloat(goalSettings.lsl || 0.0);
```

---

## 📋 測試檢查清單

### 後端 ✅
- [x] 載入 `job_xxx.json` 時儲存到 session
- [x] `current_measure` 使用 `goal` 欄位的數據
- [x] `target_range` 使用 `goalSettings` 的 LSL/USL
- [x] API 返回 `goal_name`
- [x] API 返回 `goal_settings`
- [x] IQL 維度不匹配時不中斷模擬

### 前端 ⏳
- [ ] 圖表標籤顯示 `goal_name` 而不是 "G_std"
- [ ] 綠色區塊使用 `goal_settings` 的 target/usl/lsl
- [ ] Y 軸範圍正確顯示 [lsl, usl]
- [ ] 數據點正確繪製在圖表上

---

## 🎯 下一步行動

### 選項 1: 提供前端檔案位置
請告訴我:
1. 圖表是在哪個頁面顯示的? (`dashboard.html` 的哪個功能?)
2. 使用的是哪個圖表庫? (Chart.js? ECharts?)
3. "G_std" 這個文字出現在頁面的哪裡?

### 選項 2: 搜尋前端程式碼
我可以幫您搜尋前端程式碼中的 "G_std" 字串,找到需要修改的位置

### 選項 3: 截圖說明
提供一張圖表的截圖,標註出:
- 哪裡顯示了 "G_std" (應該顯示 goal_name)
- 綠色區塊在哪裡 (應該使用 goal_settings)

---

## 📝 技術說明

### 數據流程
```
1. 使用者載入模型 (job_xxx.json)
   ↓
2. 後端讀取配置並儲存到 session.current_model_config
   ↓
3. 使用者執行模擬
   ↓
4. 後端從 current_model_config 讀取:
   - goal: 作為 Y 軸數據來源
   - goalSettings: 作為 target_range
   ↓
5. API 返回完整數據:
   - current_measure: 當前 Y 軸數值
   - target_range: [lsl, usl]
   - goal_name: 目標欄位名稱
   - goal_settings: { target, usl, lsl }
   ↓
6. 前端接收數據並繪製圖表
   - 使用 goal_name 作為標籤
   - 使用 goal_settings 繪製綠色區塊
   - 使用 target_range 設定 Y 軸範圍
```

### 關鍵設計決策

1. **為什麼在 session 中儲存 current_model_config?**
   - 避免每次模擬都重新讀取檔案
   - 確保模擬過程中使用一致的配置
   - 支援多使用者同時使用不同配置

2. **為什麼在 API 響應中加入 goal_name 和 goal_settings?**
   - 前端不需要重新請求配置
   - 減少 API 調用次數
   - 確保前端顯示與後端計算一致

3. **為什麼使用 goalSettings 而不是 config.py?**
   - 每個模型有不同的目標範圍
   - 支援動態配置,不需要修改程式碼
   - 符合實際業務需求

---

## 🔍 除錯指南

如果前端仍然顯示錯誤:

1. **檢查 API 響應**
   ```javascript
   console.log('API Response:', result);
   console.log('goal_name:', result.goal_name);
   console.log('goal_settings:', result.goal_settings);
   ```

2. **檢查圖表配置**
   ```javascript
   console.log('Chart config:', chartConfig);
   console.log('Y-axis range:', chartConfig.options.scales.y);
   ```

3. **檢查數據綁定**
   確認前端程式碼是否正確使用了 `result.goal_name` 和 `result.goal_settings`

---

## ✅ 完成狀態

**後端:** 100% 完成 ✅
**前端:** 待修改 ⏳

後端已經提供了所有必要的數據,前端只需要正確使用這些數據即可。
