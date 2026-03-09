# -*- coding: utf-8 -*-
import ast
import sys

files = [
    r"backend\services\analysis\agents\roles_v2\executor.py",
    r"backend\services\analysis\agents\roles_v2\synthesizer.py",
    r"backend\services\analysis\agents\roles_v2\strategist.py",
    r"backend\services\analysis\agents\roles_v2\planner.py",
]

all_ok = True
for f in files:
    try:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
        print(f"OK: {f}")
    except SyntaxError as e:
        print(f"FAIL: {f} -> {e}")
        all_ok = False

if all_ok:
    print("\nAll files syntax OK!")
else:
    print("\nSome files have syntax errors!")
    sys.exit(1)
