import os
import sys

# Ensure backend acts as a package
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

try:
    print("Checking LlamaIndex package availability...")
    from llama_index.utils.workflow import draw_all_possible_flows

    from backend.services.analysis.agent import SigmaAnalysisWorkflow
    from backend.services.analysis.tools.executor import ToolExecutor

    # We need a mock or simple AnalysisService to satisfy ToolExecutor
    class MockService:
        base_dir = "."

        def load_summary(self, sid, fid):
            return None

    print("Instantiating SigmaAnalysisWorkflow...")
    mock_service = MockService()
    executor = ToolExecutor(mock_service)

    # Instantiate the workflow
    workflow_instance = SigmaAnalysisWorkflow(tool_executor=executor)

    print(
        "Generating workflow visualization graph for SigmaAnalysisWorkflow instance..."
    )

    # Generate the graph
    output_path = "sigma_workflow_graph.html"
    draw_all_possible_flows(workflow_instance, filename=output_path)

    if os.path.exists(output_path):
        print(f"Successfully generated: {output_path}")
        print(f"Full path: {os.path.abspath(output_path)}")
    else:
        print("Execution finished but file not found!")

except Exception as e:
    print(f"Critical Error: {e}")
    import traceback

    traceback.print_exc()
