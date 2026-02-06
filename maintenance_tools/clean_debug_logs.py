"""
移除或註解掉過多的 DEBUG 日誌輸出
"""

import os
import re

# 需要清理的文件列表
FILES_TO_CLEAN = [
    "engine_strategy.py",
    "DataPreprocess.py",
    "api_entry.py",
    "backend/services/analysis_service.py",
    "backend/services/prediction_service.py",
]


def clean_debug_logs(file_path):
    """移除或註解掉 DEBUG 日誌"""
    if not os.path.exists(file_path):
        print(f"⚠️  檔案不存在: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    modified = False
    new_lines = []

    for i, line in enumerate(lines):
        # 檢查是否為 DEBUG print 語句
        if 'print(f"DEBUG:' in line or "print(f'DEBUG:" in line:
            # 註解掉該行
            indent = len(line) - len(line.lstrip())
            new_lines.append(" " * indent + "# " + line.lstrip())
            modified = True
            print(f"  第 {i + 1} 行: 註解掉 DEBUG print")
        # 檢查是否為 logger.debug 且內容冗長
        elif "logger.debug" in line and (
            "=" * 10 in line or "🎯" in line or "✅" in line
        ):
            # 註解掉該行
            indent = len(line) - len(line.lstrip())
            new_lines.append(" " * indent + "# " + line.lstrip())
            modified = True
            print(f"  第 {i + 1} 行: 註解掉冗長的 logger.debug")
        else:
            new_lines.append(line)

    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"✅ 已更新: {file_path}")
        return True
    else:
        print(f"ℹ️  無需修改: {file_path}")
        return False


if __name__ == "__main__":
    print("🧹 開始清理冗長的 DEBUG 日誌...\n")

    total_modified = 0
    for file_path in FILES_TO_CLEAN:
        print(f"\n處理: {file_path}")
        if clean_debug_logs(file_path):
            total_modified += 1

    print(f"\n{'=' * 60}")
    print(f"✅ 完成！共修改了 {total_modified} 個檔案")
    print(f"{'=' * 60}")
    print("\n建議：")
    print("1. 重新啟動 API 伺服器以套用變更")
    print("2. 如需要詳細除錯，可將 api_entry.py 的日誌級別改回 DEBUG")
