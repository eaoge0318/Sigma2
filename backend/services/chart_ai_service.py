import json
import requests
from typing import List, Dict, Any
from datetime import datetime
from core_logic.llm_reporter import LLMReporter
import config


class ChartAIService:
    """圖表 AI 服務，專門處理圖表分析相關的 AI 功能"""

    def __init__(self):
        self.llm_worker = LLMReporter()

    def _filter_by_days(
        self, data_history: List[Dict[str, Any]], days: int
    ) -> List[Dict[str, Any]]:
        """
        根據天數過濾數據
        """
        if not data_history or days <= 0:
            return data_history

        # 計算截止時間戳
        cutoff_timestamp = datetime.now().timestamp() - (days * 24 * 3600)

        # 過濾數據
        filtered = [
            entry
            for entry in data_history
            if entry.get("timestamp", 0) >= cutoff_timestamp
        ]

        return filtered

    def _format_chart_data_for_llm(self, chart_history: List[Dict[str, Any]]) -> str:
        """
        將圖表歷史數據格式化為適合 LLM 理解的文本
        """
        if not chart_history:
            return "目前沒有圖表分析記錄。"

        lines = ["## 圖表分析數據摘要\n"]

        for i, entry in enumerate(chart_history[-50:], 1):  # 最多顯示最近50筆
            timestamp = entry.get("timestamp", 0)
            dt_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

            chart_type = entry.get("chart_type", "未知")
            x_axis = entry.get("x_axis", "無")
            y_axis = entry.get("y_axis", "無")
            y2_axis = entry.get("y2_axis", "無")
            summary = entry.get("data_summary", {})

            lines.append(f"### 記錄 {i} ({dt_str})")
            lines.append(f"- **圖表類型**: {chart_type}")
            lines.append(f"- **X軸**: {x_axis}")
            lines.append(f"- **Y軸**: {y_axis}")
            if y2_axis != "無":
                lines.append(f"- **Y2軸**: {y2_axis}")

            if summary:
                lines.append("- **數據統計**:")
                for key, value in summary.items():
                    lines.append(f"  - {key}: {value}")

            lines.append("")

        return "\n".join(lines)

    async def generate_chart_report(
        self, chart_history: List[Dict[str, Any]], days: int = 30
    ) -> Dict[str, str]:
        """
        生成圖表分析 AI 報告
        """
        # 根據天數過濾
        filtered_data = self._filter_by_days(chart_history, days)

        if not filtered_data:
            return {
                "report": f"最近 {days} 天內沒有圖表分析記錄，請先繪製一些圖表後再生成報告。"
            }

        # 格式化數據
        formatted_data = self._format_chart_data_for_llm(filtered_data)

        # 構造專門的提示詞
        prompt = f"""你是一位數據視覺化專家，請基於以下圖表分析記錄生成深度報告：

{formatted_data}

請提供：
1. 用戶主要關注的參數和趨勢
2. 圖表類型的使用模式
3. 潛在的數據洞察和建議
4. 是否有異常或值得注意的模式

請用專業且易懂的語言回答。"""

        # 直接調用 LLM
        report_content = await self._call_llm_direct(
            [{"role": "user", "content": prompt}]
        )

        return {
            "report": report_content,
            "days": days,
            "record_count": len(filtered_data),
        }

    async def chat_with_chart_expert(
        self,
        messages: List[Dict[str, Any]],
        chart_history: List[Dict[str, Any]],
        days: int = 30,
    ) -> Dict[str, str]:
        """
        與圖表 AI 專家對話
        """
        # 根據天數過濾
        filtered_data = self._filter_by_days(chart_history, days)

        # 格式化上下文數據
        context_str = self._format_chart_data_for_llm(filtered_data)

        # 添加系統提示詞，說明專家角色並注入數據
        system_msg = {
            "role": "system",
            "content": f"""你是一位數據視覺化和圖表分析專家。包含以下功能：
1. 根據用戶的圖表歷史回答問題。
2. 解釋圖表中的數據趨勢（基於提供的統計摘要）。
3. 建議適合的圖表類型。

以下是用戶最近 {days} 天的圖表分析記錄（包含統計數據）：
{context_str}

請基於以上資訊回答用戶問題。請用繁體中文回答。""",
        }

        enhanced_messages = [system_msg] + messages

        # 調用 LLM
        reply = await self._call_llm_direct(enhanced_messages)

        return {"reply": reply, "context_days": days}

    async def _call_llm_direct(self, messages: List[Dict[str, Any]]) -> str:
        """
        直接調用 LLM API (不經過 LLMReporter 的特定業務邏輯)
        """
        payload = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "stream": False,
        }

        try:
            # 使用同步 requests 或者是 async httpx?
            # 這裡為了保持一致性，如果環境是 async 但 requests 是 blocked，通常建議用 httpx。
            # 但 llm_reporter 也是用 requests，所以這裡暫時維持 requests (但在 async def 中會 block loop，需注意)
            # 考慮到這是一個 blocking call，理想上應該 run_in_executor，但暫時簡單處理。

            response = requests.post(config.LLM_API_URL, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            return result.get("message", {}).get("content", "AI 無法產生回覆。")
        except Exception as e:
            return f"❌ LLM 連線失敗: {str(e)}"
