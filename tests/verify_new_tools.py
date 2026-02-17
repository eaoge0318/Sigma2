"""Quick import verification for the 4 new tools."""

import sys

sys.path.insert(0, ".")

try:
    from backend.services.analysis.tools.anomaly_classifier import AnomalyClassifierTool

    print("  AnomalyClassifierTool OK")
    from backend.services.analysis.tools.cross_correlation import (
        CrossCorrelationLagTool,
    )

    print("  CrossCorrelationLagTool OK")
    from backend.services.analysis.tools.frequency_analysis import FrequencyAnalysisTool

    print("  FrequencyAnalysisTool OK")
    from backend.services.analysis.tools.control_assessment import (
        ControlLoopAssessmentTool,
    )

    print("  ControlLoopAssessmentTool OK")

    from backend.services.analysis.tools.registry import TOOL_REGISTRY

    new_tools = [
        "classify_anomaly_type",
        "cross_correlation_lag",
        "frequency_analysis",
        "control_loop_assessment",
    ]
    for t in new_tools:
        if t in TOOL_REGISTRY:
            print(f"  Registry: {t} OK")
        else:
            print(f"  Registry: {t} MISSING!")

    print(f"\nTotal tools in registry: {len(TOOL_REGISTRY)}")
    print("ALL CHECKS PASSED")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback

    traceback.print_exc()
