import sys
import os
import asyncio

# 添加項目根目錄到 path
sys.path.append(os.getcwd())

from backend.services.analysis.agent import LLMAnalysisAgent
from backend.services.analysis.tools.executor import ToolExecutor
from backend.services.analysis.analysis_service import AnalysisService


async def test_init():
    print("Testing LLMAnalysisAgent initialization with LlamaIndex...")
    try:
        service = AnalysisService()
        executor = ToolExecutor(service)
        agent = LLMAnalysisAgent(executor)
        print("Success: Agent initialized successfully.")
        print(f"Registered {len(agent.tools)} tools in LlamaIndex.")

        # 測試工具名稱是否正確對接
        tool_names = [t.metadata.name for t in agent.tools]
        print(f"Tools: {', '.join(tool_names[:5])}...")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_init())
