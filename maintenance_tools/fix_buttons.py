import os

file_path = r"c:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2\dashboard.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace control buttons
old_control_1 = """                                                             <div class="move-btn"
                                                                 onclick="moveItems('control', 'to-selected')">&#10095;
                                                             </div>"""
new_control_1 = """                                                             <div id="control-to-selected-btn" class="move-btn disabled"
                                                                 onclick="moveItems('control', 'to-selected')">&#10095;
                                                             </div>"""

old_control_2 = """                                                             <div class="move-btn"
                                                                 onclick="moveItems('control', 'to-avail')">&#10094;
                                                             </div>"""
new_control_2 = """                                                             <div id="control-to-avail-btn" class="move-btn disabled"
                                                                 onclick="moveItems('control', 'to-avail')">&#10094;
                                                             </div>"""

# Replace state buttons
old_state_1 = """                                                             <div class="move-btn"
                                                                 onclick="moveItems('state', 'to-selected')">&#10095;
                                                             </div>"""
new_state_1 = """                                                             <div id="state-to-selected-btn" class="move-btn disabled"
                                                                 onclick="moveItems('state', 'to-selected')">&#10095;
                                                             </div>"""

old_state_2 = """                                                             <div class="move-btn"
                                                                 onclick="moveItems('state', 'to-avail')">&#10094;
                                                             </div>"""
new_state_2 = """                                                             <div id="state-to-avail-btn" class="move-btn disabled"
                                                                 onclick="moveItems('state', 'to-avail')">&#10094;
                                                             </div>"""

# Try to find exactly what's in the file by relaxing whitespace
import re


def flexible_replace(content, old, new):
    pattern = re.escape(old).replace(r"\ ", r"\s*").replace(r"\n", r"\s*\n\s*")
    # Since re.escape escaped spaces, we replace escaped spaces with \s*
    # We want at least some match
    return re.sub(pattern, new, content, count=1)


content = flexible_replace(content, old_control_1, new_control_1)
content = flexible_replace(content, old_control_2, new_control_2)
content = flexible_replace(content, old_state_1, new_state_1)
content = flexible_replace(content, old_state_2, new_state_2)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Replacement completed.")
