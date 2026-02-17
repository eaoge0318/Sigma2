import os
import traceback

agent_path = r"backend/services/analysis/agent.py"
chat_impl_path = r"backend/services/chat_implementation.py"

print("Starting fix_agent.py v2...")

try:
    with open(chat_impl_path, "r", encoding="utf-8", errors="ignore") as f:
        chat_code = f.read()

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
        exit(1)

    print(f"Found SigmaAnalysisWorkflow at line {workflow_idx + 1}")

    # Garbage detection: scan from END of file backwards until Workflow end?
    # Or scan forwards from Workflow start.
    # Workflow class is huge (2000 lines).
    # Garbage is at the very end.

    # Let's search from the end backwards for the LAST occurrence of "@llm_chat_callback".
    # If it's found AFTER the workflow class (i.e. line index > workflow_idx + 2000), it's garbage.

    garbage_idx = -1
    for i in range(len(lines) - 1, workflow_idx + 100, -1):
        if "@llm_chat_callback" in lines[i]:
            # Verify this is top level? Indentation check?
            # In append case, it's indented 4 spaces but inside NO class.
            garbage_idx = i
            # Once found, this is part of garbage block.
            # We want the START of this block.
            # The garbage block starts with a decorated function.
            # But there are multiple decorated functions.
            # We want the FIRST one in the sequence at the end of file.
            pass

    # Better approach:
    # Scan FORWARDS from workflow_idx + 2200.
    # The first line containing "@llm_chat_callback" is the start of garbage.

    scan_start = workflow_idx + 2000
    if scan_start >= len(lines):
        scan_start = workflow_idx + 100

    found_garbage_at = -1
    for i in range(scan_start, len(lines)):
        if "@llm_chat_callback" in lines[i]:
            # Check indentation.
            if lines[i].startswith("    @llm_chat_callback"):
                found_garbage_at = i
                break

    if found_garbage_at != -1:
        # Check if this line is basically the same as the last line? or close to end?
        print(f"Found garbage start candidate at line {found_garbage_at + 1}")
        # Truncate from here.
        # But wait, maybe there is a blank line before it?
        # We can be aggressive and truncate a few lines before if empty.
        cut_idx = found_garbage_at
        while cut_idx > scan_start and lines[cut_idx - 1].strip() == "":
            cut_idx -= 1

        print(f"Truncating file at line {cut_idx + 1}")
        lines = lines[:cut_idx]
    else:
        print("No garbage found at the end.")

    # Insert chat code
    is_already_inserted = False
    # Check 100 lines before workflow_idx for 'def chat('
    check_start = max(0, workflow_idx - 100)
    for i in range(check_range_start := check_start, workflow_idx):
        if "def chat(" in lines[i]:
            is_already_inserted = True
            print(f"Chat code already detected at line {i + 1}")
            break

    if not is_already_inserted:
        print("Inserting chat code...")
        chat_lines = chat_code.splitlines(keepends=True)
        # Ensure it starts on a new line
        to_insert = ["\n"] + chat_lines + ["\n\n"]
        lines[workflow_idx:workflow_idx] = to_insert
        print(f"Inserted {len(to_insert)} lines.")
    else:
        print("Skipping insertion.")

    with open(agent_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("Agent.py updated successfully.")

except Exception:
    traceback.print_exc()
