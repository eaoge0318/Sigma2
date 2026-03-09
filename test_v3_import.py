import sys, asyncio, traceback

sys.path.insert(0, ".")


async def test():
    try:
        from backend.services.analysis.agents.orchestrated_agent_v3 import (
            OrchestratedAnalysisAgentV3,
        )
        from backend.services.analysis.analysis_types_v3 import V3StartEvent
        from backend.services.analysis.tools.executor import ToolExecutor

        # Minimal mock
        class MockLLM:
            async def acomplete(self, *a, **kw):
                class R:
                    text = '{"restatement":"test","task_type":"global_analysis","target_params":[],"target_range":"all","suggested_tools":["combo_parameter_profiling"],"clarification_question":null}'

                return R()

        te = ToolExecutor.__new__(ToolExecutor)
        w = OrchestratedAnalysisAgentV3(llm=MockLLM(), tool_executor=te)

        ev = V3StartEvent(query="hello", file_id="test", session_id="test")
        handler = w.run(v3_start_event=ev)
        print("run() OK, handler type:", type(handler))

        # Try streaming
        async for event in handler.stream_events():
            print("Event:", type(event).__name__)

    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()


asyncio.run(test())
