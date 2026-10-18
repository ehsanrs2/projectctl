#!/usr/bin/env python3
"""Verify only public, synthetic fixture structure and behavior.

Never opens the private oracle or guesses the number of hidden defects.
The frozen source_bundle/scripts/validate_bundle.py remains unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BUNDLE = Path(__file__).resolve().parent.parent / "source_bundle"
CASES = tuple(f"case-{i:02d}" for i in range(1, 7))
FILES = ("SPEC.md", "case.json", "module.py", "test_module.py")


def main() -> int:
    root = BUNDLE / "fixtures"
    if not root.is_dir():
        print("FAIL: missing fixtures", file=sys.stderr)
        return 2
    actual = {p.name for p in root.iterdir() if p.is_dir()}
    if actual != set(CASES):
        print(f"FAIL: expected {CASES}; got {sorted(actual)}", file=sys.stderr)
        return 2
    for case in CASES:
        source = root / case
        for name in FILES:
            p = source / name
            if not p.is_file() or p.is_symlink():
                print(f"FAIL: missing/unsafe {case}/{name}", file=sys.stderr)
                return 2
        config = json.loads((source / "case.json").read_text(encoding="utf-8"))
        if config.get("case_id") != case:
            print(f"FAIL: incorrect case identity {case}", file=sys.stderr)
            return 2
        with tempfile.TemporaryDirectory(prefix="pctl-research-public-fixture-") as d:
            dst = Path(d)
            for name in FILES:
                shutil.copy2(source / name, dst / name)
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-p", "test_module.py", "-v"],
                cwd=dst, capture_output=True, text=True, timeout=30, check=False,
            )
        if result.returncode != 0:
            print(f"FAIL: {case}\n{result.stdout}\n{result.stderr}", file=sys.stderr)
            return 2
        print(f"{case}: PASS")
    print("PUBLIC FIXTURES: PASS (oracle not accessed; no defect scores computed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
