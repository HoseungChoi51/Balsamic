#!/bin/bash
# Cloud sessions only: install what the Python tests need, once, before the session starts (docs/testing in the brief).
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "$CLAUDE_PROJECT_DIR"

# bubblewrap is the package sandbox; without it about 100 tests fail with SandboxUnavailable.
if ! command -v bwrap >/dev/null; then
  apt-get update -qq && apt-get install -y -qq bubblewrap
fi

uv sync -q --extra dev
# scipy and matplotlib come with the meent extra, whose meent the cloud cannot reach; pytest-xdist runs the suite in
# parallel. Into the environment, not `uv run --with`: a sandboxed test runs the environment's Python.
uv pip install -q scipy==1.18.1 "matplotlib>=3.10,<4" "pytest-xdist>=3.6,<4"

# The launcher tests refuse root and run as the container's normal user, who needs to read the checkout.
chmod -R a+rX "$CLAUDE_PROJECT_DIR" 2>/dev/null || true

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export GRATING_LLM_DISABLED=true' >> "$CLAUDE_ENV_FILE"
fi
