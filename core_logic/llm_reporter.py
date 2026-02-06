import json
import requests

# import httpx  # 移除 httpx 依賴，改用 requests + asyncio
import numpy as np
import pandas as pd
import config
from .domain_knowledge import EXPERT_RULES


def numpy_converter(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


class LLMReporter:
    def __init__(self):
        self.api_url = config.LLM_API_URL
        self.model = config.LLM_MODEL

    async def generate_report(self, history_data):
        """
        將歷史數據組合成 Prompt 並發送給 LLM 進行診斷
        history_data: 最近 50 筆的診斷紀錄
        """
        if not history_data:
            return "目前沒有數據，請先啟動系統以收集數據。"

        # 1. 提取關鍵摘要資訊
        latest = history_data[-1]
        count = len(history_data)
        # 從歷史數據中提取 measure_name,如果沒有則使用預設值
        measure_name = latest.get("measure_name", "目標值")

        # 組合 Prompt
        prompt = f"""
你是一位製程診斷專家。請結合以下【專家領域知識】與【即時數據摘要】（目標欄位: {measure_name}），給予專業報告。

### 專家領域知識 (SOP/文獻規律) ###
{EXPERT_RULES}

**重要提醒 (嚴格遵守)**:
- **禁止臆測**: 嚴禁對任何參數代碼 (如 PM21、A472 等) 進行含義推測。除非數據中明確包含中文描述，否則不准使用"乾燥效率"、"壓力"、"真空度"等術語。
- **客觀描述**: 必須使用「參數 [原始代碼] 上升/下降」的客觀格式。
- **機號屏蔽**: 避免在報告中提及 PM21 等特定機號。
- **領域知識限制**: 領域知識僅作為數據趨勢分析的「方法論」參考，不准用來對當前代碼進行「名詞解釋」。

### 數據快照 ###
- 當前 {measure_name} 數值: {latest.get("current_measure", "N/A")}
- 診斷結論: {latest.get("diagnosis", "N/A")}
- 建議操作建議: {json.dumps(latest.get("recommendations", {}), ensure_ascii=False)}

### 歸因分析 (SHAP) ###
- 當前影響因子: {latest.get("current_top_influencers", [])}
- 10筆趨勢因子: {latest.get("smoothed_top_influencers", [])}

### 歷史趨勢 ({measure_name}) ###
"""
        # 增加最近幾筆的趨勢讓 LLM 參考
        trend_count = min(count, 10)
        for i, rec in enumerate(history_data[-trend_count:]):
            prompt += f"- [{i}] {measure_name}: {rec.get('current_measure', 'N/A')}, 狀態: {rec.get('status', 'N/A')}\n"

        prompt += f"""
請針對以上資訊，用『繁體中文』進行『極簡報式』回答（不超過 300 字，避開冗長描述）：
1. 波動核心原因 (條列重點,對於未知參數只報告變化,不推測意義)。
2. 操作員具體建議 (基於 SHAP 分析結果,建議關注哪些參數)。
3. 未來 10 分鐘介入必要性 (是/否，原因)。

**回答準則**:
- 對於明確對應到領域知識的參數，可以使用專業術語解釋
- 對於無法對應的參數代碼，只報告其數值變化，不要臆測其意義
- 注意：請一律使用 {measure_name} 稱呼測量值
"""

        # 2. 發送請求給 Ollama (使用異步)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        # 使用 asyncio 在線程池中執行同步請求，避免阻塞事件循環
        import asyncio

        def _make_request():
            """在線程池中執行的同步 HTTP 請求"""
            try:
                # 超時時間設定為 30 秒
                response = requests.post(self.api_url, json=payload, timeout=30.0)
                response.raise_for_status()
                result = response.json()
                return result.get("message", {}).get("content", "無法取得 AI 回覆內容")
            except requests.exceptions.Timeout:
                return f"❌ LLM 請求超時 (30s)。LLM 服務可能負載過高或模型太大，請稍後再試。\nURL: {self.api_url}"
            except requests.exceptions.ConnectionError:
                return f"❌ LLM 連線失敗。請檢查 LLM 服務是否啟動，或 IP 設定是否正確。\nURL: {self.api_url}"
            except Exception as e:
                return f"❌ LLM 調用失敗: {str(e)}\nURL: {self.api_url}"

        # 在線程池中執行請求，避免阻塞 FastAPI 事件循環
        loop = asyncio.get_running_loop()  # 改用 get_running_loop
        result = await loop.run_in_executor(
            None, _make_request
        )  # None 使用默認 executor
        return result

    def chat_with_expert(self, messages, context_data):
        """
        與 AI 專家進行連續對話，具備 [Python 計算代理] 功能
        1. 自動解析意圖 (相關性、統計)
        2. 後端 Python 直接計算精確數值
        3. 注入真實數據陣列供繪圖
        """
        # --- DEBUG LOGGING ---
        import logging

        logging.basicConfig(
            filename="llm_debug.log",
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            encoding="utf-8",
        )

        try:
            measure_name = (
                context_data[-1].get("measure_name", "目標值")
                if context_data
                else "目標值"
            )
            user_msg = messages[-1]["content"] if messages else ""

            # 若無數據，直接回覆
            if not context_data:
                return "目前系統尚無歷史數據 (0 筆)，無法進行計算分析。"

            # --- A. 數據庫建置 (DataFrame) ---
            # 提取 feature_snapshots 中的所有鍵值
            # 為了處理可能的漏值，先收集所有可能的 columns
            all_keys = set()
            cleaned_history = []

            for record in context_data:
                snaps = record.get("feature_snapshots", {})
                # 確保目標值也在內
                snaps[measure_name] = record.get("current_measure", 0.0)
                for k in snaps.keys():
                    all_keys.add(k)
                cleaned_history.append(snaps)

            df = pd.DataFrame(cleaned_history)
            # 填補 NaN (以防萬一)
            df.fillna(method="ffill", inplace=True)
            df.fillna(0.0, inplace=True)

            # --- B. 智慧欄位匹配 (Fuzzy Match & Auto-Context) ---
            relevant_columns = []
            latest = context_data[-1]

            # 1. 擴充搜尋範圍：只看 USER 的最近 3 句 (忽略 AI 自己的回覆，以免遞迴匹配太多參數)
            user_msgs = [
                m.get("content", "") for m in messages[-3:] if m.get("role") == "user"
            ]
            recent_text = " ".join(user_msgs).lower()

            # 2. 預設加入: 目標值 + Top 3 影響因子 (確保一定有數據可畫，不會空白)
            relevant_columns.append(measure_name)
            top_influencers = [
                f.split(" (")[0] for f in latest.get("current_top_influencers", [])
            ]
            relevant_columns.extend(top_influencers[:3])

            # 3. 掃描所有欄位
            # 建立關鍵字表
            keywords = (
                recent_text.replace("，", " ")
                .replace("。", " ")
                .replace("？", "")
                .split()
            )

            for col in all_keys:
                if col in relevant_columns:
                    continue
                col_lower = col.lower()

                # 規則 1: 欄位名直接出現在近期對話中
                if col.lower() in recent_text:
                    relevant_columns.append(col)
                    continue

                # 規則 2: 關鍵字命中
                for kw in keywords:
                    if len(kw) < 2:
                        continue
                    if any(c.isascii() and c.isalnum() for c in kw):
                        if kw in col_lower:
                            relevant_columns.append(col)
                            break

            # 去重
            relevant_columns = list(set(relevant_columns))

            # 限制最大引用欄位數 (防止 Context Overflow)
            if len(relevant_columns) > 7:
                priority = {measure_name}
                influencers = [
                    f.split(" (")[0] for f in latest.get("current_top_influencers", [])
                ]
                priority.update(influencers[:5])

                final_cols = [c for c in relevant_columns if c in priority]
                for c in relevant_columns:
                    if len(final_cols) >= 7:
                        break
                    if c not in final_cols:
                        final_cols.append(c)
                relevant_columns = final_cols
            logging.info(f"User Query Context: {recent_text}")
            logging.info(f"Matched Columns: {relevant_columns}")

            # --- C. Python 計算代理 (Math Engine) ---
            # 2026-01-29 Update: 注入全域參數清單，避免 AI 以為只有這幾個參數
            all_exist_cols = list(df.columns)
            total_col_count = len(all_exist_cols)
            # 為了節省 Token，如果參數太多 (>50)，可以只列出前 50 個或做摘要，這裡先全列
            global_param_info = f"【系統全域參數資訊】(共 {total_col_count} 個): {str(all_exist_cols)}\n"

            calc_report = (
                global_param_info
                + "【系統後端自動計算報告】(請基於以下數值回覆，勿自行幻覺):\n"
            )

            # 1. 統計摘要
            for col in relevant_columns:
                if col not in df.columns:
                    continue
                series = df[col]
                avg = series.mean()
                std = series.std()
                curr = series.iloc[-1]
                # 加強版統計：最大、最小、中位數
                stat_max = series.max()
                stat_min = series.min()
                stat_median = series.median()
                stat_q1 = series.quantile(0.25)
                stat_q3 = series.quantile(0.75)

                calc_report += (
                    f"- {col}: 現值={curr:.4f}, 平均={avg:.4f}, Std={std:.4f}, "
                    f"Max={stat_max:.4f}, Min={stat_min:.4f}, Median={stat_median:.4f}, "
                    f"Q1={stat_q1:.4f}, Q3={stat_q3:.4f}\n"
                )

            # 2. 相關性計算 (如果提到 "相關" 且有 >=2 個欄位)
            # 2026-01-29 Update: 優先計算「目標變數」與其他欄位的相關性，解決 "答非所問" 問題
            if len(relevant_columns) >= 2:
                calc_report += "\n[相關係數偵測 (Pearson Correlation)]:\n"

                # A. 優先計算: 目標 (Measure) vs 其他特徵 (Features)
                target_corrs = []
                for col in relevant_columns:
                    if col == measure_name:
                        continue
                    if col not in df.columns:
                        continue

                    # 計算與目標值的相關性
                    if measure_name in df.columns:
                        r = df[measure_name].corr(df[col])
                        target_corrs.append((measure_name, col, r))

                # 排序 (絕對值由大到小)
                target_corrs.sort(key=lambda x: abs(x[2]), reverse=True)

                # 寫入報告
                for t, c, val in target_corrs:
                    calc_report += f"  * ★ {t} vs {c} = {val:.4f}\n"

                # B. 次要計算: 其他兩兩相關 (Feature vs Feature)
                # 只有當 User 明確選了其他欄位時才補充顯示，避免資訊過載
                for i in range(len(relevant_columns)):
                    for j in range(i + 1, len(relevant_columns)):
                        c1, c2 = relevant_columns[i], relevant_columns[j]
                        if c1 == measure_name or c2 == measure_name:
                            continue  # 前面算過了
                        if c1 not in df.columns or c2 not in df.columns:
                            continue

                        r = df[c1].corr(df[c2])
                        # 只顯示高度相關 (>0.7) 的配角關係，減少雜訊
                        if abs(r) > 0.7:
                            calc_report += f"  * (次要) {c1} vs {c2} = {r:.4f}\n"

            # --- D. 數據注入 (Data Injection for Charts) ---
            # 為了讓 LLM 畫圖，我們必須把這些欄位的 raw data (10點) 印出來
            # 格式: Name: [1.1, 2.2, ...]
            # --- 動態調整數據長度 (Adaptive Data Window) ---
            # 根據使用者問的參數數量，決定要給多少歷史數據
            # 少參數 -> 給長趨勢 (30點)
            # 多參數 -> 給短趨勢 (10點) 以節省 Token
            num_vars = len(relevant_columns)
            # --- Retry Loop (Smart Fallback) ---
            # 嘗試最多 2 次:
            #   Attempt 1: 正常設定 (根據 num_vars 調整 10/20/30)
            #   Attempt 2: 救援模式 (Top3 變數 + 5筆數據)

            max_retries = 2
            final_reply = ""

            for attempt in range(1, max_retries + 1):
                is_rescue_mode = attempt == 2

                # --- Step 1: 決定 history_limit 與 欄位 ---
                current_relevant_cols = relevant_columns.copy()

                if not is_rescue_mode:
                    # 正常模式: 沿用前面的 adaptive logic
                    if num_vars <= 3:
                        history_limit = 30
                    elif num_vars <= 5:
                        history_limit = 20
                    else:
                        history_limit = 10
                else:
                    # 救援模式: 強制縮減
                    history_limit = 5
                    # 同時只保留最重要的前 3 個欄位 (Measure + Top2 Influencers)
                    # 確保 relevant_columns 裡面的目標值優先保留
                    priority_keys = [measure_name]
                    if len(top_influencers) >= 1:
                        priority_keys.append(top_influencers[0])
                    if len(top_influencers) >= 2:
                        priority_keys.append(top_influencers[1])

                    # 過濾
                    current_relevant_cols = [
                        c for c in current_relevant_cols if c in priority_keys
                    ]
                    # 如果過濾完太少，至少補回原本的前3個
                    if len(current_relevant_cols) < min(3, len(relevant_columns)):
                        current_relevant_cols = relevant_columns[:3]

                # --- Step 2: 構建 Data Injection String ---
                data_injection_str = "\n【可用繪圖數據 (JSON Array Format)】:\n"
                if is_rescue_mode:
                    data_injection_str += "(注意: 由於系統負載過高，已自動切換至[救援模式]，僅顯示關鍵 Top3 參數與近期 5 筆數據)\n"

                data_injection_str += (
                    "(若需繪製 Chart.js，請**直接複製**以下陣列，嚴禁省略)\n"
                )

                for col in current_relevant_cols:
                    if col not in df.columns:
                        continue
                    valid_len = min(history_limit, len(df))
                    values = df[col].tail(valid_len).tolist()
                    vals_str = "[" + ", ".join([f"{v:.4f}" for v in values]) + "]"
                    data_injection_str += f"- {col} (len={valid_len}): {vals_str}\n"

                # --- Step 3: 重新計算 System Context ---
                # (需要重新組合，因為 data_injection_str 變了)
                system_context = f"""你是一位擁有計算能力的資料科學助手。
系統已在後端通過 Python 完成了精確計算，請閱讀下方的【系統後端自動計算報告】。

{calc_report}

{data_injection_str}

【回覆準則】:
1. **事實優先**: 當你回答相關係數、平均值等統計數據時，必須**完全依據**上方的 [系統後端自動計算報告]，**嚴禁**自行心算或猜測。
2. **圖表繪製**:
   - 請回傳標準 JSON 格式 (type: chart)。
   - **必須嚴格遵守以下 JSON 結構**:
     趨勢圖: `{{"type": "chart", "chart_type": "line", "title": "標題", "datasets": [{{"label": "名稱", "data": [1.1, 2.2]}}]}}`
     散佈圖: `{{"type": "chart", "chart_type": "scatter", "title": "標題", "datasets": [{{"label": "X軸名", "data": [...]}}, {{"label": "Y軸名", "data": [...]}}]}}`
     *注意: 散佈圖必須且只能包含兩個 dataset (X 與 Y)，前端會自動合併。*

   - 在 `data` 陣列中，請**直接複製**上方【可用繪圖數據】中的數值，**嚴禁**使用 "..." 縮寫。
   - `labels` 欄位可以省略，前端會自動生成。
   - **重要的繪圖限制**: 請只繪製使用者**明確詢問**的 1~2 個變數，不用把所有數據都畫出來。
3. **對話語氣**: 專業、客觀。如果算出來相關係數很低 (如 0.1)，就直說是低相關，不要因為使用者預設它很高就附和。
4. **後續建議**: 在每次回答的最後，請務必包含一個「建議後續分析」區塊，提供 3 個具體、可行的後續問題或分析方向，引導使用者深入挖掘數據意義。
5. **零臆測原則 (Zero-Guessing Principle)**: 
   - 系統中包含大量代碼 (如 PM21_XXX, A123 等)，**嚴禁**對其進行任何含義猜測。
   - 不准提及 PM21 等機號字眼。
   - 如果參數沒有中文註解，必須直呼其代碼並報告數據。
   - 嚴禁自行將『A123』對應到理論中的『真空度』。
"""
                full_messages = [
                    {"role": "system", "content": system_context}
                ] + messages
                payload = {
                    "model": self.model,
                    "messages": full_messages,
                    "stream": False,
                }

                # --- Step 4: 發送請求 ---
                try:
                    logging.info(
                        f"Sending request (Attempt {attempt}/{max_retries})..."
                    )
                    json_data = json.dumps(payload, default=numpy_converter)

                    response = requests.post(
                        self.api_url,
                        data=json_data,
                        headers={"Content-Type": "application/json"},
                        timeout=90,  # 保持 90s
                    )
                    response.raise_for_status()
                    result = response.json()
                    final_reply = result.get("message", {}).get("content", "").strip()

                    # 成功收到回覆，跳出迴圈
                    if final_reply:
                        return final_reply

                except Exception as e:
                    import traceback

                    logging.warning(f"Attempt {attempt} failed: {str(e)}")
                    if attempt == max_retries:
                        # 最後一次也失敗，才拋出錯誤
                        err_str = str(e)
                        if (
                            "Connection refused" in err_str
                            or "Failed to establish a new connection" in err_str
                        ):
                            error_msg = f"❌ LLM 連線失敗 (已重試 {max_retries} 次)。請檢查服務是否啟動。\nURL: {self.api_url}"
                        elif "Read timed out" in err_str:
                            error_msg = f"❌ LLM 請求超時 (已重試 {max_retries} 次)。\nURL: {self.api_url}"
                        else:
                            error_msg = f"❌ 對話調用失敗 (已重試): {err_str}\nURL: {self.api_url}"

                        print(error_msg)
                        return error_msg
                    else:
                        # 還有機會，繼續下一次迴圈 (進入救援模式)
                        continue

            return "AI 專家目前無法回覆，請嘗試縮短問法。"

        except Exception as e:
            # 外層捕捉所有邏輯運算錯誤
            import traceback

            error_msg = f"Critical Chat Logic Error: {str(e)}\n{traceback.format_exc()}"
            logging.error(error_msg)
            return f"❌ 系統發生預期外錯誤: {str(e)}"


if __name__ == "__main__":
    # 簡單測試連線
    reporter = LLMReporter()
    test_msg = "你好，這是一則製程機器人的測試訊息。"
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": test_msg}],
        "stream": False,
    }
    print(f"正在測試連線至 {config.LLM_API_URL} ...")
    try:
        r = requests.post(config.LLM_API_URL, json=payload, timeout=5)
        print("連線成功！回覆内容：", r.json()["message"]["content"])
    except Exception as e:
        print("連線失敗：", e)
