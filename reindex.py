import asyncio
import sys
import os
import logging

# 將當前目錄加入 path，以便導入 backend
sys.path.append(os.getcwd())

from backend.services.analysis.analysis_service import AnalysisService


async def main():
    # 設置日誌以查看輸出
    logging.basicConfig(level=logging.INFO)

    service = AnalysisService(base_dir="workspace")
    session_id = "Mantle"
    file_id = "26af199d9132"

    # 診斷映射表
    print("--- 診斷映射表 ---")
    mapping = service._load_mapping_table(session_id)
    print(f"找到 {len(mapping)} 個映射項")
    if mapping:
        print(f"範例: {list(mapping.items())[:3]}")
        # 檢查斷紙
        break_matches = [v for k, v in mapping.items() if "斷紙" in v]
        print(f"包含 '斷紙' 的對應: {break_matches[:5]}")

    print(f"\nRe-indexing session: {session_id}, file: {file_id}...")
    success = await service.manual_reindex(session_id, file_id)
    if success:
        print("Re-indexing completed successfully!")

        # 檢查生成後的 semantic_index
        index = service.load_semantic_index(session_id, file_id)
        if "斷紙" in index:
            print(f"✅ '斷紙' 已成功索引，對應欄位: {index['斷紙']}")
        else:
            print("❌ '斷紙' 仍然不在索引中")
    else:
        print("Failed to re-index. File not found.")


if __name__ == "__main__":
    asyncio.run(main())
