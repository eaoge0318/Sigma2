try:
    file_path = r"c:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2\static\js\dashboard_full.js"
    keywords = ["chat-input", "keydown", "Enter", "handleChatKey"]

    print(f"Analyzing {file_path}...")
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        line_num = i + 1
        content = line.strip()
        # Find keywords
        hits = [k for k in keywords if k in content]
        if hits:
            # Print with context (surrounding lines handled mentally, just print matching line)
            print(f"{line_num}: [{', '.join(hits)}] {content[:100]}")
            found = True

    if not found:
        print("No matches found.")

except Exception as e:
    print(f"Error: {e}")
