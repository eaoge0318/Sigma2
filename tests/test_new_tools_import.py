"""Verify all new tool imports"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []

# Test 1: correlation_network
try:
    from backend.services.analysis.tools.correlation_network import (
        CorrelationNetworkTool,
    )

    results.append("PASS: correlation_network")
except Exception as e:
    results.append(f"FAIL: correlation_network - {e}")

# Test 2: cv_ranking
try:
    from backend.services.analysis.tools.cv_ranking import CVRankingTool

    results.append("PASS: cv_ranking")
except Exception as e:
    results.append(f"FAIL: cv_ranking - {e}")

# Test 3: regime_detection
try:
    from backend.services.analysis.tools.regime_detection import RegimeDetectionTool

    results.append("PASS: regime_detection")
except Exception as e:
    results.append(f"FAIL: regime_detection - {e}")

# Test 4: multi_objective
try:
    from backend.services.analysis.tools.multi_objective import MultiObjectiveTool

    results.append("PASS: multi_objective")
except Exception as e:
    results.append(f"FAIL: multi_objective - {e}")

# Test 5: executor (all tools registered)
try:
    from backend.services.analysis.tools.executor import ToolExecutor

    results.append("PASS: executor (all imports OK)")
except Exception as e:
    results.append(f"FAIL: executor - {e}")

with open("tests/import_results_v2.txt", "w") as f:
    f.write("\n".join(results) + "\nDONE\n")

print("Test complete - see tests/import_results_v2.txt")
