import os

agent_path = r"backend/services/analysis/agent.py"

print("Starting binary cleanup of agent.py...")

try:
    with open(agent_path, "rb") as f:
        content = f.read()

    print(f"Read {len(content)} bytes.")

    # Find marker: "class SigmaAnalysisWorkflow"
    marker = b"class SigmaAnalysisWorkflow"

    # We want to keep everything up to the end of the class.
    # But how do we know where the class ends?
    # The garbage was appended AFTER the class.
    # The garbage starts with specific bytes sequence.
    # In UTF-16 LE, typical chars are 0xXX 0x00.
    # The garbage starts with "@llm_chat_callback".
    # In UTF-16: 0x40 0x00 ...

    # Let's search for the UTF-16 version of "@llm_chat_callback".
    garbage_marker_utf16 = "@llm_chat_callback".encode("utf-16-le")

    idx = content.rfind(garbage_marker_utf16)

    if idx != -1:
        print(f"Found UTF-16 garbage at offset {idx}. Truncating...")
        # Check if there's BOM before it?
        # Usually BOM is FF FE.
        # Check a few bytes before idx.
        start_cut = idx
        if idx >= 2 and content[idx - 2 : idx] == b"\xff\xfe":
            start_cut = idx - 2

        # Truncate
        new_content = content[:start_cut]

        # Verify end of file is clean (remove trailing whitespace/nulls)
        new_content = new_content.rstrip()

        with open(agent_path, "wb") as f:
            f.write(new_content)
        print("Truncated successfully.")
    else:
        print("No UTF-16 garbage found. Checking for UTF-8 garbage...")
        # Maybe it was appended as UTF-8 but I missed it?
        garbage_marker_utf8 = b"@llm_chat_callback"
        # Search for LAST occurrence.
        idx = content.rfind(garbage_marker_utf8)

        # We need to distinguish between valid usage (inside class) and garbage (at end).
        # Valid usage is indented. Garbage is also indented?
        # But garbage is AFTER SigmaAnalysisWorkflow.
        # Find SigmaAnalysisWorkflow offset.
        workflow_idx = content.find(marker)
        if workflow_idx == -1:
            print("Warning: SigmaAnalysisWorkflow class not found.")
            exit(1)

        # If garbage is found way after workflow starts (e.g. > 200000 bytes later), it's suspicious?
        # No, file size is ~130KB.

        # Check if the found marker is near the end of file.
        if idx != -1 and idx > len(content) - 5000:
            print(f"Found UTF-8 garbage candidate at {idx}. Truncating...")
            new_content = content[:idx].rstrip()
            with open(agent_path, "wb") as f:
                f.write(new_content)
            print("Truncated.")
        else:
            print("No garbage found.")

except Exception as e:
    import traceback

    traceback.print_exc()
