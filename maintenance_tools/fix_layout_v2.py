import re

filepath = r"c:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2\dashboard.html"
with open(filepath, "rb") as f:
    raw_data = f.read()

# Try to decode safely
try:
    content = raw_data.decode("utf-8")
except UnicodeDecodeError:
    content = raw_data.decode("big5", errors="ignore")

# Use very loose regex to find the step 1 area
# We look for the h3 and the select box and the flex box.
panel_re = r'(<div id="train-step-panel-1".*?>\s*)(<h3.*?>.*?第一步：🎯.*?標的</h3>)\s*(<div.*?選擇標的欄位.*?</div>)\s*(<div.*?display: flex; gap: 20px;.*?SCATTER PREVIEW.*?</div>)\s*(<div.*?規格參數配置.*?</div>)\s*(</div>)'

# Let's try something even simpler. Find the Specs Config div and move it.
# Or just wrap the whole thing.

# We'll search for the specific parts.
part1 = re.search(r"<h3.*?>.*?第一步：🎯.*?任務標的</h3>", content, re.DOTALL)
part2 = re.search(
    r"<div[^>]*?>\s*<label[^>]*?>\s*<span[^>]*?>🎯</span> 選擇標的欄位.*?</div>",
    content,
    re.DOTALL,
)
part3 = re.search(
    r"<div[^>]*?display: flex; gap: 20px;.*?SCATTER PREVIEW.*?</div>",
    content,
    re.DOTALL,
)
part4 = re.search(r"<div[^>]*?🎯 規格參數配置.*?</div>\s*</div>", content, re.DOTALL)

if part1 and part2 and part3 and part4:
    # Build new structure
    new_panel = (
        part1.group(0)
        + "\n"
        + '<div style="display: flex; gap: 20px; flex: 1; min-height: 0; margin-bottom: 10px;">\n'
        + '  <div style="flex: 1; display: flex; flex-direction: column; gap: 10px; min-width: 0;">\n'
        + "    "
        + part2.group(0)
        + "\n"
        + "    "
        + part3.group(0)
        + "\n"
        + "  </div>\n"
        + "  "
        + part4.group(0)
        + "\n"
        + "</div>"
    )

    # Replace the old block from start of h3 to end of row
    start_pos = part1.start()
    end_pos = part4.end()

    final_content = content[:start_pos] + new_panel + content[end_pos:]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(final_content)
    print("Success")
else:
    print("Failed to find all parts")
    if not part1:
        print("Missing part1")
    if not part2:
        print("Missing part2")
    if not part3:
        print("Missing part3")
    if not part4:
        print("Missing part4")
