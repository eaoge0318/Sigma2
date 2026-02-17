import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.analysis.agents.roles.designer import DesignerRole
from backend.services.analysis.analysis_types import (
    AnalysisContext,
    RoleInput,
    AnalysisState,
    StepResult,
)


class MockLLM:
    async def achat(self, messages):
        return type(
            "Response", (), {"message": type("Message", (), {"content": "{}"})}
        )()

    async def acomplete(self, prompt):
        return type("Response", (), {"text": "{}"})()


async def main():
    # Mock Context
    context = AnalysisContext(
        targets=["MEDIC-DCS_A1006"],
        feature_pool=[],
        focus_range=None,
        baseline_range=None,
    )

    # Mock State
    state = AnalysisState(
        session_id="test",
        file_id="test",
        original_query="test",
        strategy_plan="test",
        current_context=context,
        causal_chain=[],
        analysis_roadmap=[],
        status="running",
    )

    # Mock Evidence from Hotelling T2
    mock_evidence = {
        "primary_anomaly_range": [42, 48],
        "top_contributors": [
            {"parameter": "FORMULA-DCS_A15", "contribution": 0.85},
            {"parameter": "MEDIC-DCS_A1006", "contribution": 0.15},
        ],
    }

    state.history.append(
        StepResult(
            role="Specialist",
            tool_name="hotelling_t2_analysis",
            evidence=mock_evidence,
            conclusion="Found anomaly",
        )
    )

    # Run Designer
    role = DesignerRole(llm=MockLLM())
    input_data = RoleInput(state_machine=state, directive="CONTINUE")

    result = await role.execute(input_data)

    print("Decision:", result.decision)
    print("New Targets:", result.new_context.targets)
    print("New Focus Range:", result.new_context.focus_range)
    try:
        print("Reasoning:", result.reasoning)
    except UnicodeEncodeError:
        print("Reasoning:", result.reasoning.encode("utf-8", errors="ignore"))


if __name__ == "__main__":
    asyncio.run(main())
