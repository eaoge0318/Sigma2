"""
AI 服務
負責 LLM 報告生成和對話
"""

from typing import List, Dict, Any
from core_logic.llm_reporter import LLMReporter


class AIService:
    """AI 服務，處理 LLM 相關的業務邏輯"""

    def __init__(self):
        self.llm_worker = LLMReporter()

    async def generate_report(
        self, history_data: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        生成 AI 報告

        Args:
            history_data: 歷史數據

        Returns:
            報告內容
        """
        if not history_data:
            return {"report": "目前沒有數據，請先啟動系統以收集數據。"}

        recent_data = history_data[-50:]

        # generate_report 本身就是 async 函數，直接 await 即可
        report_content = await self.llm_worker.generate_report(recent_data)
        return {"report": report_content}

    async def chat_with_expert(
        self, messages: List[Dict[str, Any]], context_data: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        與 AI 專家對話

        Args:
            messages: 對話訊息
            context_data: 上下文數據

        Returns:
            AI 回覆
        """
        import asyncio

        # 使用 asyncio.to_thread 將同步的 LLM 請求移至線程池執行，避免阻塞事件循環
        reply = await asyncio.to_thread(
            self.llm_worker.chat_with_expert, messages, context_data
        )
        return {"reply": reply}

    async def summarize_scatter_grid(
        self, x_axis: str, y_axis: str, grid_groups: Dict[str, List[str]]
    ) -> Dict[str, str]:
        """
        利用 AI 摘要九宮格中各個區塊的參數名稱關鍵字。
        """
        import json
        import requests
        import asyncio
        import config

        prompt = f"""
你是一位工業製造與數據分析領域的參數分類專家。
現在有一組參數，根據與「{x_axis}」及「{y_axis}」的相關係數高低，被分到了九個象限區塊中。
請觀察每個區塊中的「參數名稱」（通常蘊含了機台部位、物理量等），為每個區塊總結出 3~5 個 最核心代表性的「關鍵字」，並且在每個區塊的最終總結後面加上「...」。
（例如：機台溫度, 氣體流量, 主蒸汽, 閥門開度...）

以下是九宮格（以左上到右下排列）中包含的參數清單：
"""
        for k, v in grid_groups.items():
            param_str = ", ".join(v[:30])  # 取前 30 個避免過長
            if len(v) > 30:
                param_str += "..."
            prompt += f"- {k} ({len(v)}個): {param_str}\n"

        prompt += """
請只回傳合法的 JSON 格式，不要包含任何其他廢話或 markdown 標記（如 ```json）。
格式範例：
{
  "top_left": "關鍵字1, 關鍵字2",
  "top_center": "...",
  "top_right": "...",
  "mid_left": "...",
  "center": "...",
  "mid_right": "...",
  "bottom_left": "...",
  "bottom_center": "...",
  "bottom_right": "..."
}
"""
        payload = {
            "model": config.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        def _make_request():
            try:
                response = requests.post(config.LLM_API_URL, json=payload, timeout=45.0)
                response.raise_for_status()
                res_json = response.json()
                if "choices" in res_json:
                    # OpenAI API schema
                    res_content = res_json["choices"][0].get("message", {}).get("content", "{}")
                else:
                    # Ollama API schema
                    res_content = res_json.get("message", {}).get("content", "{}")
                
                res_content = res_content.strip()
                if res_content.startswith("```json"):
                    res_content = res_content.split("```json", 1)[1]
                elif res_content.startswith("```"):
                    res_content = res_content.split("```", 1)[1]
                if res_content.endswith("```"):
                    res_content = res_content.rsplit("```", 1)[0]
                res_content = res_content.strip()

                try:
                    parsed = json.loads(res_content)
                    return parsed
                except Exception:
                    # 如果只能解析失敗，直接回傳字串當作 error
                    return {"error": "解析 AI 回覆的 JSON 失敗"}
                
            except Exception as e:
                return {"error": f"LLM 請求錯誤: {str(e)}"}

        try:
            result = await asyncio.to_thread(_make_request)
            return result
        except Exception as e:
            return {"error": str(e)}
