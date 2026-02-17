import os
import traceback

agent_path = r"backend/services/analysis/agent.py"

print("Starting agent.py cleanup...")

try:
    with open(agent_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        lines = content.splitlines(keepends=True)

    print(f"Read {len(lines)} lines from agent.py.")

    workflow_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("class SigmaAnalysisWorkflow"):
            workflow_idx = i
            break

    if workflow_idx == -1:
        print("Error: Could not find SigmaAnalysisWorkflow class.")
        # Try to find class definition using broader search
        for i, line in enumerate(lines):
            if "class SigmaAnalysisWorkflow" in line:
                workflow_idx = i
                break

    if workflow_idx == -1:
        print("Fatal: Cannot find SigmaAnalysisWorkflow.")
        exit(1)

    print(f"Found SigmaAnalysisWorkflow at line {workflow_idx + 1}")

    # Garbage detection: scan for @llm_chat_callback AFTER the workflow class body.
    # SigmaAnalysisWorkflow is ~2400 lines long.
    # We search from the end backwards, or from workflow_idx + 2000 forwards.

    garbage_start_idx = -1
    found_garbage = False

    # Robust search: Look for lines that look like "    @llm_chat_callback()"
    # appearing after line 2500 (assuming valid code ends around there).

    scan_start = max(workflow_idx + 100, len(lines) - 200)  # Search last 200 lines

    for i in range(scan_start, len(lines)):
        if "@llm_chat_callback" in lines[i]:
            garbage_start_idx = i
            found_garbage = True
            break

    if found_garbage:
        print(f"Found garbage starting at line {garbage_start_idx + 1}. Truncating...")
        # Check if previous lines are empties
        cut_idx = garbage_start_idx
        while cut_idx > scan_start and lines[cut_idx - 1].strip() == "":
            cut_idx -= 1
        lines = lines[:cut_idx]

        with open(agent_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print("Cleanup successful.")
    else:
        print("No garbage found at the end. File seems clean.")

except Exception:
    traceback.print_exc()
