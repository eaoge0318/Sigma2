import os

file_path = r"c:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2\dashboard.html"
css_link = '    <link rel="stylesheet" href="/static/css/styles.css?v=final_fix">\n'
js_script = '    <script src="/static/js/dashboard.js?v=final_fix"></script>\n'

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
in_style = False
in_script = False
style_replaced = False
script_replaced = False

# We know specific regions roughly.
# Style is approx 17-1231
# Script is approx 1980-4391

i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    # Check for Style Start
    if stripped == "<style>" and not style_replaced:
        in_style = True
        new_lines.append(css_link)
        style_replaced = True
        i += 1
        continue

    if in_style:
        if stripped == "</style>":
            in_style = False
            # Don't keep the closing tag line
        i += 1
        continue

    # Check for Main Script Start
    # We ignore the top scripts. Only match <script> alone on a line (maybe with whitespace)
    if stripped == "<script>" and not script_replaced:
        # Check if there are imports before. Imports usually have src=...
        # The main script tag has no src.
        if "src=" not in line:
            # We assume this is the main script block
            in_script = True
            new_lines.append(js_script)
            script_replaced = True
            i += 1
            continue

    if in_script:
        if stripped == "</script>":
            in_script = False
            # Don't keep closing tag
        i += 1
        continue

    new_lines.append(line)
    i += 1

with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("dashboard.html updated successfully.")
