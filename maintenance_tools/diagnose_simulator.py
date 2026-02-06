"""
診斷腳本 - 檢查模擬功能的 Y 軸配置
"""

import requests
import json

# 設定
BASE_URL = "http://localhost:8001"
SESSION_ID = "Mantle"

print("=" * 60)
print("診斷模擬功能 Y 軸配置")
print("=" * 60)

# 1. 檢查可用的模型
print("\n1. 檢查可用的模型...")
try:
    response = requests.get(
        f"{BASE_URL}/api/simulator/models", params={"session_id": SESSION_ID}
    )
    if response.ok:
        models = response.json()
        print(f"   找到 {len(models)} 個模型:")
        for model in models[:3]:
            print(f"   - {model.get('name', model.get('id'))}")
    else:
        print(f"   ❌ 錯誤: {response.status_code}")
except Exception as e:
    print(f"   ❌ 異常: {e}")

# 2. 載入一個模型配置
print("\n2. 載入模型配置...")
model_to_load = "job_7ba3af9e.json"  # 請根據實際情況修改
try:
    response = requests.post(
        f"{BASE_URL}/api/model/load",
        json={"model_path": model_to_load, "session_id": SESSION_ID},
    )
    if response.ok:
        result = response.json()
        print(f"   ✅ {result.get('message')}")
    else:
        error_data = response.json()
        print(f"   ❌ 錯誤: {error_data.get('detail')}")
except Exception as e:
    print(f"   ❌ 異常: {e}")

# 3. 檢查模型配置檔案內容
print("\n3. 檢查模型配置檔案...")
config_path = f"workspace/{SESSION_ID}/configs/{model_to_load}"
try:
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    print(f"   goal 欄位: {config.get('goal')}")
    print(f"   filename: {config.get('filename')}")
    print(f"   model_name: {config.get('model_name')}")
except Exception as e:
    print(f"   ❌ 無法讀取配置: {e}")

# 4. 載入模擬檔案
print("\n4. 載入模擬檔案...")
sim_file = "KL00(AVG)(1).csv"  # 請根據實際情況修改
try:
    response = requests.post(
        f"{BASE_URL}/api/simulator/load_file",
        json={"filename": sim_file, "session_id": SESSION_ID},
    )
    if response.ok:
        result = response.json()
        print(f"   ✅ {result.get('message')} ({result.get('rows')} 筆)")
    else:
        error_data = response.json()
        print(f"   ❌ 錯誤: {error_data.get('detail')}")
except Exception as e:
    print(f"   ❌ 異常: {e}")

# 5. 執行一次模擬並檢查輸出
print("\n5. 執行模擬並檢查 Y 軸數據...")
try:
    response = requests.post(
        f"{BASE_URL}/api/simulator/next", json={"session_id": SESSION_ID}
    )
    if response.ok:
        result = response.json()
        print(f"   current_measure: {result.get('current_measure')}")
        print(f"   status: {result.get('status')}")
        print(f"   ✅ 模擬成功")
    else:
        error_data = response.json()
        print(f"   ❌ 錯誤: {error_data.get('detail')}")
except Exception as e:
    print(f"   ❌ 異常: {e}")

print("\n" + "=" * 60)
print("診斷完成")
print("=" * 60)
print("\n請檢查伺服器的 console 輸出,查找以下訊息:")
print("  - [DEBUG] Goal column from model config: ...")
print("  - [DEBUG] Using goal column '...' as measure: ...")
print("  - [WARNING] Goal column not found in session or data...")
