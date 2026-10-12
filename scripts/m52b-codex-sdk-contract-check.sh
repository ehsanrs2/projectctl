#!/usr/bin/env bash
# Run after: uv pip install -e ".[dev,codex]"
# This is the *actual* optional SDK contract gate: fail rather than skip when
# the pinned import is absent. No worker execution or remote API is performed.
set -euo pipefail

if [[ ! -f pyproject.toml || ! -f docs/PROJECT_STATE.yaml ]]; then
  echo "Run from the ProjectCTL repository root." >&2
  exit 2
fi

PYTHON="${PYTHON:-python3}"

"${PYTHON}" - <<'PY'
import importlib.metadata
import sys
import openai_codex

assert sys.version_info >= (3, 12), "ProjectCTL requires Python >=3.12"
actual = importlib.metadata.version("openai-codex")
assert actual == "0.160.0", f"Expected openai-codex 0.160.0, found {actual}"
print(f"Pinned Codex SDK importable; version={actual}")
PY

"${PYTHON}" -m pytest -q \
  tests/test_m12b_codex_sdk_contract.py \
  tests/test_m12b_codex_adapter.py

echo "Pinned Codex SDK public contract and adapter checks passed."
