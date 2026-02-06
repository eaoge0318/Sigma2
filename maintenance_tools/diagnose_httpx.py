"""
診斷 Python 環境和 httpx 安裝狀態
"""

import sys
import subprocess

print("=" * 60)
print("Python 環境診斷")
print("=" * 60)

# 1. Python 版本和路徑
print(f"\n1. Python 版本: {sys.version}")
print(f"   Python 路徑: {sys.executable}")

# 2. 已安裝的套件
print("\n2. 檢查 httpx 安裝狀態:")
try:
    import httpx

    print(f"   ✅ httpx 已安裝")
    print(f"   版本: {httpx.__version__}")
except ImportError:
    print(f"   ❌ httpx 未安裝")

# 3. 嘗試安裝 httpx
print("\n3. 嘗試安裝 httpx:")
try:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "httpx"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(f"   返回碼: {result.returncode}")
    if result.returncode == 0:
        print(f"   ✅ 安裝成功!")
    else:
        print(f"   ❌ 安裝失敗")
        print(f"   錯誤: {result.stderr}")
except Exception as e:
    print(f"   ❌ 安裝過程出錯: {e}")

# 4. 再次檢查
print("\n4. 再次檢查 httpx:")
try:
    import httpx

    print(f"   ✅ httpx 現在可用!")
    print(f"   版本: {httpx.__version__}")
except ImportError:
    print(f"   ❌ httpx 仍然不可用")
    print(f"\n建議:")
    print(f"   請手動執行: {sys.executable} -m pip install httpx")

print("\n" + "=" * 60)
