import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    print("Attempting to import OrchestratedAnalysisAgentV2...")
    from backend.services.analysis.agents.orchestrated_agent_v2 import (
        OrchestratedAnalysisAgentV2,
    )

    print("Import successful!")
except Exception as e:
    print(f"Import failed: {e}")
    import traceback

    traceback.print_exc()
