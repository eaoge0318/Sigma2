try:
    import reward_engine

    print("Successfully imported reward_engine")
    import config

    print(f"Config dir: {dir(config)}")
except Exception as e:
    print(f"Import failed: {e}")
