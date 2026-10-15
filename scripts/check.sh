#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check backend/app backend/tests
.venv/bin/ruff format --check backend/app backend/tests backend/migrations
(cd backend && ../.venv/bin/pytest -q)
if [ -f spec/call_policy_simulator.py ]; then
  (cd spec && ../.venv/bin/python -m unittest -v call_policy_simulator.py)
fi
