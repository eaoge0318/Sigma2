from backend.services.analysis.agents.roles_v3.code_analyst import (
    CodeAnalyst,
    SCENARIO_CONFIG,
    anomaly_complete,
    optimization_complete,
    drift_complete,
    exploratory_complete,
    try_loose_json,
)

print("Import OK")
print("Scenarios:", list(SCENARIO_CONFIG.keys()))

# Test 3-layer validation
print("\n--- anomaly_complete ---")
print("Strict pass:", anomaly_complete("", {"primary_column": "X", "primary_z": 3.0}))
print("Semantic pass:", anomaly_complete("z=3.45 TEMP-DCS_A12", {}))
print("Fail:", anomaly_complete("no evidence", {}))

print("\n--- optimization_complete ---")
print(
    "Strict pass:",
    optimization_complete("", {"primary_column": "X", "conclusion": "操作窗口建議"}),
)
print("Keyword pass:", optimization_complete("", {"conclusion": "驅動因子排名"}))
print("Fail:", optimization_complete("nothing", {}))

print("\n--- drift_complete ---")
print(
    "Strict pass:",
    drift_complete("slope=0.5", {"primary_column": "X", "conclusion": "漂移"}),
)
print("Fail:", drift_complete("nothing", {}))

print("\n--- exploratory_complete ---")
print("Pass:", exploratory_complete("", {"conclusion": "建議深入分析三個方向"}))
print("Fail:", exploratory_complete("", {"conclusion": ""}))

print("\n--- try_loose_json ---")
print("Trailing comma:", try_loose_json('{"a": 1,}'))
print("Single quotes:", try_loose_json("{'a': 1}"))
print("None:", try_loose_json("not json"))

print("\n--- Prompt build ---")
a = CodeAnalyst(None)
p = a._build_prompt("test query", {"row_count": 100}, task_type="anomaly_detection")
print(f"Prompt len: {len(p)} chars")
print("Has L1 (Execution Contract):", "硬規則" in p)
print("Has L2 (Scenario Policy):", "異常診斷" in p)
print("Has L3 (Tools):", "sigma.find_anomalies" in p)
print("NO Chain of Thought:", "分析戰略設計書" not in p)
