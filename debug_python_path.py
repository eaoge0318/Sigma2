import sys
from llama_index.core.workflow import Context

try:
    print("Context dir:", dir(Context))
    # Try to inspect 'store'
    print("Context.store type:", type(Context.store))
    print("Context.store doc:", getattr(Context.store, "__doc__", "No doc"))

    # Try instantiation if possible (might fail if args needed)
    try:
        ctx = Context()
        print("Context instantiated. dir(ctx):", dir(ctx))
        if hasattr(ctx, "data"):
            print("ctx.data:", ctx.data)
    except Exception as e:
        print(f"Instantiation failed: {e}")

except Exception as e:
    print(f"Error: {e}")
