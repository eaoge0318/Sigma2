try:
    # Try common locations for DictState
    from llama_index.core.workflow.state import DictState
except ImportError:
    try:
        from llama_index.core.workflow.context import DictState
    except ImportError:
        print("Could not import DictState directly.")
        DictState = None

if DictState:
    print("DictState dir:", dir(DictState))
else:
    # Try to find it via Context
    from llama_index.core.workflow import Context

    # We can't easily get the type object from the property reference without an instance,
    # but the docstring mentioned it.
    pass
