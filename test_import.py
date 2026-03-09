import sys
import traceback

try:
    from backend.routers import analysis_router

    print("OK: analysis_router imported successfully")
except Exception as e:
    with open("import_error.txt", "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    print(f"FAILED: {e}")
    traceback.print_exc()
