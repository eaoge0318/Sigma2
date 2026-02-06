"""
測試 AI 助手 API 是否正常工作
"""

import requests
import json

# 設定
API_BASE = "http://localhost:8001"
SESSION_ID = "default"


def test_ai_report():
    """測試 AI 報告生成"""
    print("=" * 60)
    print("測試 1: AI 報告生成")
    print("=" * 60)

    url = f"{API_BASE}/api/ai_report?session_id={SESSION_ID}"
    print(f"請求 URL: {url}")

    try:
        response = requests.get(url, timeout=30)
        print(f"HTTP 狀態碼: {response.status_code}")

        if response.ok:
            data = response.json()
            print("\n回應內容:")
            print(json.dumps(data, ensure_ascii=False, indent=2))

            if "report" in data:
                print(f"\n✅ 報告長度: {len(data['report'])} 字元")
                print(f"\n報告預覽 (前 200 字):")
                print(data["report"][:200])
            else:
                print("\n❌ 回應中沒有 'report' 欄位")
        else:
            print(f"❌ 請求失敗: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ 連線失敗：無法連接到 API 伺服器")
        print(f"   請確認伺服器是否在 {API_BASE} 運行")
    except requests.exceptions.Timeout:
        print("❌ 請求超時 (30秒)")
    except Exception as e:
        print(f"❌ 發生錯誤: {type(e).__name__}: {e}")


def test_ai_chat():
    """測試 AI 對話"""
    print("\n" + "=" * 60)
    print("測試 2: AI 對話")
    print("=" * 60)

    url = f"{API_BASE}/api/ai_chat"
    print(f"請求 URL: {url}")

    payload = {
        "messages": [{"role": "user", "content": "你好，這是測試訊息"}],
        "session_id": SESSION_ID,
    }

    print(f"\n請求內容:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    try:
        response = requests.post(url, json=payload, timeout=60)
        print(f"\nHTTP 狀態碼: {response.status_code}")

        if response.ok:
            data = response.json()
            print("\n回應內容:")
            print(json.dumps(data, ensure_ascii=False, indent=2))

            if "reply" in data:
                print(f"\n✅ 回覆長度: {len(data['reply'])} 字元")
            else:
                print("\n❌ 回應中沒有 'reply' 欄位")
        else:
            print(f"❌ 請求失敗: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ 連線失敗：無法連接到 API 伺服器")
        print(f"   請確認伺服器是否在 {API_BASE} 運行")
    except requests.exceptions.Timeout:
        print("❌ 請求超時 (60秒)")
    except Exception as e:
        print(f"❌ 發生錯誤: {type(e).__name__}: {e}")


def test_llm_connection():
    """測試 LLM 服務連線"""
    print("\n" + "=" * 60)
    print("測試 3: LLM 服務連線檢查")
    print("=" * 60)

    # 從 config.py 讀取 LLM URL
    import sys

    sys.path.insert(0, ".")
    try:
        import config

        llm_url = config.LLM_API_URL
        llm_model = config.LLM_MODEL

        print(f"LLM URL: {llm_url}")
        print(f"LLM 模型: {llm_model}")

        # 測試連線
        test_payload = {
            "model": llm_model,
            "messages": [{"role": "user", "content": "test"}],
            "stream": False,
        }

        print(f"\n嘗試連接到 LLM 服務...")
        response = requests.post(llm_url, json=test_payload, timeout=10)

        if response.ok:
            print("✅ LLM 服務連線正常")
            print(f"   HTTP 狀態碼: {response.status_code}")
        else:
            print(f"❌ LLM 服務回應錯誤")
            print(f"   HTTP 狀態碼: {response.status_code}")
            print(f"   錯誤訊息: {response.text[:200]}")

    except requests.exceptions.ConnectionError:
        print(f"❌ 無法連接到 LLM 服務")
        print(f"   URL: {llm_url}")
        print(f"   可能原因:")
        print(f"   1. Ollama 服務未啟動")
        print(f"   2. IP 地址或端口設定錯誤")
        print(f"   3. 網路連線問題")
    except requests.exceptions.Timeout:
        print("❌ LLM 服務連線超時")
    except ImportError:
        print("❌ 無法載入 config.py")
    except Exception as e:
        print(f"❌ 發生錯誤: {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("🧪 開始測試 AI 助手功能")
    print()

    # 先測試 LLM 連線
    test_llm_connection()

    # 再測試 API
    test_ai_report()
    test_ai_chat()

    print("\n" + "=" * 60)
    print("測試完成")
    print("=" * 60)
