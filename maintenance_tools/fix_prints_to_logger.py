# fix_prints_to_logger.py
"""批量替换 print 为 logger"""

import re

# 读取文件
with open("agent_logic.py", "r", encoding="utf-8") as f:
    content = f.read()

# 替换规则
replacements = [
    (r'print\(f"ℹ️', 'logger.info("ℹ️'),
    (r'print\(f"✅', 'logger.info("✅'),
    (r'print\(f"⚠️', 'logger.warning("⚠️'),
    (r'print\(f"❌', 'logger.error("❌'),
    (r'print\(f"🔄', 'logger.info("🔄'),
    (r'print\(f"🔍', 'logger.debug("🔍'),
    (r'print\(f"🎯', 'logger.debug("🎯'),
    (r'print\(f"Session ID:', 'logger.debug("Session ID:'),
    (r'print\(f"IQL Model', 'logger.debug("IQL Model'),
    (r'print\(f"Simulator', 'logger.debug("Simulator'),
    (r'print\(f"XGBoost', 'logger.debug("XGBoost'),
    (r'print\(f"BG Features', 'logger.debug("BG Features'),
    (r'print\(f"Action STDs', 'logger.debug("Action STDs'),
    (r'print\(f"Current Y', 'logger.debug("Current Y'),
    (r'print\(f"   -', 'logger.info("   -'),
    (r'print\(f"  -', 'logger.info("  -'),
    (r'print\(f"   Reason', 'logger.error("   Reason'),
    (r'print\(f"Failed to', 'logger.error("Failed to'),
    (r'print\(f"Loading specific', 'logger.info("Loading specific'),
    (r'print\(f"AgenticReasoning', 'logger.info("AgenticReasoning'),
    (r'print\(f"\n\{', 'logger.debug("\\n{'),
    (r"print\(f'\{", "logger.debug('{"),
]

for pattern, replacement in replacements:
    content = re.sub(pattern, replacement, content)

# 写回文件
with open("agent_logic.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ 替换完成！")
