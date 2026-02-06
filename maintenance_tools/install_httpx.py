"""
自動診斷並安裝 httpx 到當前 Python 環境
"""

import sys
import subprocess

print("=" * 60)
print("Python 環境診斷與 httpx 安裝")
print("=" * 60)

# 1. 顯示當前 Python 資訊
print(f"\n當前 Python 版本: {sys.version}")
print(f"Python 執行檔路徑: {sys.executable}")

# 2. 檢查 httpx 是否已安裝
print("\n檢查 httpx 狀態...")
try:
    import httpx

    print(f"✅ httpx 已安裝,版本: {httpx.__version__}")
    print("\n後端應該可以啟動了!")
    sys.exit(0)
except ImportError:
    print("❌ httpx 未安裝在此環境中")

# 3. 嘗試安裝 httpx
print("\n正在安裝 httpx...")
try:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "httpx"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode == 0:
        print("✅ httpx 安裝成功!")

        # 驗證安裝
        try:
            import httpx

            print(f"✅ 驗證成功! httpx 版本: {httpx.__version__}")
            print("\n現在可以啟動後端了:")
            print(f"  python api_entry.py")
        except ImportError:
            print("⚠️ 安裝完成但無法 import,可能需要重新啟動 Python")
    else:
        print(f"❌ 安裝失敗!")
        print(f"錯誤訊息: {result.stderr}")

except Exception as e:
    print(f"❌ 安裝過程出錯: {e}")

print("\n" + "=" * 60)
input("\n按 Enter 鍵退出...")
