import pytest
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Add root directory to path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.ai_service import AIService

# Simulation data
MOCK_HISTORY = [{"measure_name": "Test", "current_measure": 100}]


@pytest.mark.asyncio
async def test_generate_report_no_data():
    """測試沒有數據時的情況"""
    service = AIService()
    # Mock LLMReporter to avoid real init overhead
    service.llm_worker = MagicMock()

    result = await service.generate_report([])
    assert "report" in result
    assert "沒有數據" in result["report"]


@pytest.mark.asyncio
async def test_generate_report_success():
    """測試正常生成報告 (驗證 Async Fix)"""
    service = AIService()

    # 這裡是最關鍵的 Mock
    # llm_worker.generate_report 是 async 方法，所以要用 AsyncMock
    service.llm_worker = MagicMock()
    service.llm_worker.generate_report = AsyncMock(return_value="AI Report Content")

    result = await service.generate_report(MOCK_HISTORY)

    # 驗證是否正確調用
    service.llm_worker.generate_report.assert_called_once()
    assert result["report"] == "AI Report Content"


@pytest.mark.asyncio
async def test_chat_with_expert():
    """測試對話功能 (驗證同步轉異步)"""
    service = AIService()

    # chat_with_expert 是同步方法，但在 ai_service 中被包裝成異步
    # 所以我們 mock 這個同步方法
    service.llm_worker = MagicMock()
    service.llm_worker.chat_with_expert = MagicMock(return_value="Chat Reply")

    messages = [{"role": "user", "content": "Hi"}]
    context = []

    result = await service.chat_with_expert(messages, context)

    # 驗證是否調用
    service.llm_worker.chat_with_expert.assert_called_once()
    assert result["reply"] == "Chat Reply"
