import asyncio
from typing import Any
from backend.services.analysis.agent import SigmaAnalysisWorkflow
from backend.services.analysis.analysis_types import (
    MonologueEvent,
    IntentEvent,
    AnalysisEvent,
)


class MockToolExecutor:
    def __init__(self, analysis_service):
        self.analysis_service = analysis_service

    def list_tools(self):
        return [
            {
                "name": "mock_tool",
                "description": "A mock tool",
                "required_params": ["p1"],
            }
        ]

    def execute_tool(self, name, params, session_id):
        return {
            "mock_result": "success",
            "params": params,
            "top_3_summary": "Mock Top 3: p1(0.5)",
        }


class MockAnalysisService:
    def load_summary(self, session_id, file_id):
        return {
            "filename": "test.csv",
            "total_rows": 500,
            "parameters": ["p1", "p2", "ID", "TIME"],
            "mappings": {"p1": "壓力感測器", "p2": "流量感測器"},
            "categories": {"SENSOR": ["p1", "p2"]},
            "quality_stats": {
                "null_column_count": 0,
                "constant_column_count": 0,
                "sparse_column_count": 0,
            },
        }


async def main():
    print("--- Starting SigmaAnalysisWorkflow Test ---")

    # 1. Mock Dependencies
    analysis_service = MockAnalysisService()
    tool_executor = MockToolExecutor(analysis_service)

    # 2. Define Event Handler
    async def event_handler(ev):
        print(f"\n[EventHandler] Received Event: {type(ev).__name__}")
        if isinstance(ev, MonologueEvent):
            print(f"  Monologue: {ev.monologue}")
            print(f"  Tool: {ev.tool_name}")
            print(f"  Params: {ev.tool_params}")

    # 3. Instantiate Workflow
    workflow = SigmaAnalysisWorkflow(
        tool_executor=tool_executor,
        analysis_service=analysis_service,
        event_handler=event_handler,
        verbose=True,
    )

    # Mock LLM to return valid JSON for plan_analysis
    # We can't easily mock LLM inside the class unless we patch it or subclass.
    # SigmaAnalysisWorkflow.__init__ initializes Ollama.
    # To avoid real LLM calls (which might fail or be slow), we should mock self.llm.

    class MockLLM:
        async def acomplete(self, prompt):
            # Return a valid JSON response for plan_analysis
            class Response:
                text = '{"monologue": "Test monologue", "tool": "mock_tool", "params": {"p1": "v1"}}'

            return Response()

    workflow.llm = MockLLM()

    # 4. Run Workflow
    # We need to trigger the workflow.
    # route_intent might fail if we don't mock it or provide correct input.
    # Let's bypass route_intent and call plan_analysis directly?
    # No, we must run via .run() or step-by-step.
    # But .run() starts at StartEvent.

    # To test plan_analysis logic specifically, we can manually trigger it?
    # No, workflow.run is the standard way.
    # route_intent will start. It uses LLM too.
    # We need to make sure MockLLM handles route_intent prompt too.

    class SmartMockLLM:
        async def acomplete(self, prompt):
            class Response:
                text = ""

            prompt_str = str(prompt)
            if "Classify the intent" in prompt_str:
                Response.text = "ANALYSIS"
            elif "Internal Monologue" in prompt_str:
                Response.text = '{"monologue": "Test monologue", "tool": "mock_tool", "params": {"p1": "v1"}}'
            elif "summarize" in prompt_str.lower():
                Response.text = "Summary of analysis."
            else:
                Response.text = "{}"
            return Response()

    workflow.llm = SmartMockLLM()

    print("Running workflow with query='Analyze data'...")
    try:
        result = await workflow.run(query="Analyze data", file_id="f1", session_id="s1")
        print(f"\nWorkflow Final Result: {result}")
    except Exception as e:
        print(f"\nWorkflow Failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
