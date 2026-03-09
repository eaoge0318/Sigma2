import pathlib

p = pathlib.Path(r"backend/services/analysis/agent.py")
raw = p.read_bytes()

# The problematic pattern: _state_key(ev.session_id, ev.file_id)\r\r\n
# Should be: _state_key(ev.session_id, ev.file_id)\r\n
bad = b"ev.file_id)\\r\r\n"
good = b"ev.file_id)\r\n"

count = raw.count(bad)
print(f"Found {count} occurrences of bad pattern")

if count > 0:
    raw = raw.replace(bad, good)
    p.write_bytes(raw)
    print("Fixed!")
else:
    # Try alternate pattern
    bad2 = b"ev.file_id)\\\r\r\n"
    count2 = raw.count(bad2)
    print(f"Alt pattern: {count2} occurrences")
    if count2 > 0:
        raw = raw.replace(bad2, good)
        p.write_bytes(raw)
        print("Fixed with alt pattern!")
