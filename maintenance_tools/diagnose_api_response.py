"""
診斷前端圖表問題 - 檢查 API 返回的數據
"""

import requests
import json

BASE_URL = "http://localhost:8001"
SESSION_ID = "Mantle"

print("=" * 60)
print("診斷前端圖表 Y 軸問題")
print("=" * 60)

# 執行一次模擬並查看返回的數據
print("\n執行模擬並檢查返回數據...")
try:
    response = requests.post(
        f"{BASE_URL}/api/simulator/next", json={"session_id": SESSION_ID}
    )

    if response.ok:
        result = response.json()
        print(f"\n✅ 模擬成功")
        print(f"\n關鍵欄位:")
        print(f"  - status: {result.get('status')}")
        print(f"  - current_measure: {result.get('current_measure')}")
        print(f"  - target_range: {result.get('target_range')}")
        print(f"  - predicted_y_next: {result.get('predicted_y_next')}")

        print(f"\n完整返回數據:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"❌ 錯誤: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"❌ 異常: {e}")

print("\n" + "=" * 60)
print("診斷完成")
print("=" * 60)
print("\n請檢查:")
print("1. current_measure 的數值是否正確 (應該是 2.x)")
print("2. 前端是否正確使用 current_measure 來繪製圖表")
print("3. 前端圖表的數據源是什麼")
