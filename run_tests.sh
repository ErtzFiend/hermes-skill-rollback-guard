#!/usr/bin/env bash
# Runs the hermes-skill-rollback-guard test suite against a Hermes checkout.
#
#   HERMES_SRC=/path/to/hermes-agent ./run_tests.sh
#
# The real-loader tests exercise Hermes' own discovery/import/register path and the
# tool_execution middleware chain, under a disposable HERMES_HOME. No core file is touched.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_SRC="${HERMES_SRC:-/usr/local/lib/hermes-agent}"

if [[ ! -d "$HERMES_SRC/agent" ]]; then
  echo "ERROR: Hermes source not found at $HERMES_SRC (set HERMES_SRC)" >&2
  exit 2
fi
HERMES_PYTHON="${HERMES_PYTHON:-python3}"
command -v "$HERMES_PYTHON" >/dev/null || { echo "ERROR: $HERMES_PYTHON not found" >&2; exit 2; }
"$HERMES_PYTHON" -c "import pytest, ruamel.yaml" 2>/dev/null || {
  echo "ERROR: $HERMES_PYTHON needs pytest + ruamel.yaml (pip install pytest ruamel.yaml pyyaml)" >&2
  exit 2
}

echo "Running hermes-skill-rollback-guard tests (HERMES_SRC=$HERMES_SRC)..."
HERMES_HOME="$(mktemp -d)" \
HERMES_SRC="$HERMES_SRC" \
PYTHONPATH="$HERMES_SRC:$PLUGIN_DIR" \
PYTHONDONTWRITEBYTECODE=1 \
  "$HERMES_PYTHON" -m pytest "$PLUGIN_DIR/tests" "$@"
echo "All tests passed."
