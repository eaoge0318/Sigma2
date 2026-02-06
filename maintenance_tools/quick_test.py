import requests
import json

response = requests.get("http://localhost:8001/api/ai_report?session_id=default")
print(f"Status Code: {response.status_code}")
print(f"Content-Type: {response.headers.get('Content-Type')}")
print(f"\nResponse (decoded):")
data = response.json()
print(json.dumps(data, ensure_ascii=False, indent=2))
