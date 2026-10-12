#!/usr/bin/env bash
# M5.2b closure gate: run from a genuine local checkout with Python >= 3.12.
set -euo pipefail

if [[ ! -f pyproject.toml || ! -f docs/PROJECT_STATE.yaml ]]; then
  echo "Run this script from the ProjectCTL repository root." >&2
  exit 2
fi

PYTHON="${PYTHON:-python3}"
"${PYTHON}" -c 'import sys; assert sys.version_info >= (3, 12), "ProjectCTL requires Python 3.12+"'
echo "M5.2b gate: targeted scope, historical and execution regressions"
"${PYTHON}" -m pytest -q \
  tests/test_m52b_scope_migration.py \
  tests/test_m52b_scope_enforcement.py \
  tests/test_m52b_scope_foundation.py \
  tests/test_m51_context_adoption.py \
  tests/test_m50_context_discovery.py \
  tests/test_m42a_execution_inputs.py \
  tests/test_m41a_parallel_planning.py \
  tests/test_m41b_parallel_runtime.py \
  tests/test_m14_integration_recovery.py \
  tests/test_m13_verify_e2e.py \
  tests/test_schema_export.py

echo "M5.2b gate: complete test suite"
"${PYTHON}" -m pytest -q

echo "M5.2b gate: patch hygiene"
git diff --check "${BASE_REF:-main}...HEAD"

echo "M5.2b local closure checks passed."
echo "Record this command's exit code, Python version, Git commit SHA and test output."
echo "Passing locally does not imply GitHub Actions or architecture acceptance."
