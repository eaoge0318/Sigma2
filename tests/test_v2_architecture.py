import asyncio
import sys
import os
import json
from typing import Any, Dict

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.analysis.agents.orchestrated_agent_v2 import (
    OrchestratedAnalysisAgentV2,
)
from backend.services.analysis.analysis_types import (
    StartEvent,
    AnalysisState,
    RoleOutput,
    AnalysisReport,
    ExperimentContext,
    Evidence,
)


class MockLLM:
    """
    Simulates LLM responses for different roles based on the prompt content.
    """

    async def acomplete(self, prompt: str, json_mode: bool = False, **kwargs):
        # Determine which role is asking based on prompt keywords
        if "Strategist" in prompt or "策略指揮" in prompt or "Dashboard" in prompt:
            return self._strategist_response()
        elif "Experiment Planner" in prompt or "實驗規劃師" in prompt:
            return self._planner_response()
        elif "Synthesizer" in prompt or "綜合分析師" in prompt:
            return self._synthesizer_response()
        else:
            # Default fallback
            return type("Response", (), {"text": "{}"})()

    def _strategist_response(self):
        # Strategist decides to check Trend
        resp = {
            "thought": "Mock Strategist thinking...",
            "decision": "CONTINUE",
            "directive": "Analyze the trend of A257 and check for anomalies.",
            "reasoning": "Initial scan required.",
        }
        return type("Response", (), {"text": json.dumps(resp)})()

    def _planner_response(self):
        # Planner designs 2 experiments
        resp = {
            "thought": "Mock Planner thinking...",
            "experiments": [
                {
                    "id": "EXP-001",
                    "objective": "Check Trend",
                    "technique": "Trend Analysis",
                    "target_columns": ["A257"],
                    "focus_range": "Global",
                },
                {
                    "id": "EXP-002",
                    "objective": "Check Anomalies",
                    "technique": "Distribution Analysis",
                    "target_columns": ["A257"],
                    "focus_range": "30-50",
                },
            ],
            "reasoning": "Planning trend and distribution check.",
        }
        return type("Response", (), {"text": json.dumps(resp)})()

    def _synthesizer_response(self):
        # Synthesizer reviews expectations
        resp = {
            "thought": "Mock Synthesizer reviewing...",
            "key_findings": [
                "A257 shows upward trend.",
                "Anomaly detected in 30-50 range.",
            ],
            "next_step_suggestion": "Investigate correlation with B103.",
            "synthesis_logic": "Evidence suggests systemic shift.",
            "decision": "CONTINUE",  # Continues loop (or FINISH to stop)
        }
        return type("Response", (), {"text": json.dumps(resp)})()


class MockToolExecutor:
    """
    Simulates tool execution.
    """

    async def execute_tool(self, tool_name: str, params: Dict, session_id: str):
        print(f"  [MockToolExecutor] Executing {tool_name} with {params}")
        if tool_name == "draw_trend":
            return {"result": "Trend is UP", "evidence": "Slope > 0.5"}
        elif tool_name == "compare_distributions":
            return {
                "result": "Distribution Shift Detected",
                "evidence": "KS-Test p < 0.05",
            }
        else:
            return {"result": "Done", "evidence": "Executed"}


class MockAnalysisService:
    def is_generation_stopped(self, session_id):
        return False


async def main():
    print(
        "=== Testing V2 Architecture (Strategist -> Planner -> Executor -> Synthesizer) ==="
    )

    # 1. Setup Mocks
    mock_llm = MockLLM()
    mock_executor = MockToolExecutor()
    mock_service = MockAnalysisService()

    # 2. Init Agent
    agent = OrchestratedAnalysisAgentV2(mock_llm, mock_executor, mock_service)

    # 3. Create Start Event
    start_event = StartEvent(
        query="Analyze A257", file_id="test_file", session_id="test_session"
    )
    summary_data = {
        "n_rows": 100,
        "columns": ["A257", "B103", "Yield"],
        "dtypes": ["float", "float", "float"],
    }

    # 4. Run Loop (Limit to 2 turns to prevent infinite loop if mocks allow)
    print("\n--- Starting Run ---")
    step_count = 0
    async for event in agent.run_analysis(start_event, summary_data):
        if isinstance(event, dict):  # Final Result
            print("\n[FINAL RESULT]")
            print(event["response"])
            break

        print(f"[Event] {type(event).__name__}")
        if hasattr(event, "monologue"):
            print(f"  Monologue: {event.monologue[:100]}...")
        if hasattr(event, "msg"):
            print(f"  Msg: {event.msg}")

        # Construct a stopping condition for the test
        if "【綜合驗收】" in getattr(event, "monologue", ""):
            step_count += 1
            if step_count >= 1:  # Let it run 1 full turn then stop
                print("\n[Test Interruption] forcing stop after 1 turn.")
                break


if __name__ == "__main__":
    asyncio.run(main())
