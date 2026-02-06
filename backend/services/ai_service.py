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
