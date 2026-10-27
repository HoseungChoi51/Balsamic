#!/usr/bin/env bash
set -euo pipefail
# The workspace's coding harness and its mode, as the host set them (roadmap H2). Only pi has an adapter (decision 8).
harness="${BALSAMIC_HARNESS:-pi}"
mode="${BALSAMIC_HARNESS_MODE:-tui}"
if [ "$harness" != pi ]; then
    echo "The coding harness \"$harness\" is not available: a coding workspace runs only pi. Another harness needs its own adapter, opted into per workspace on the researcher's own credentials mounted read-only." >&2
    exit 78
fi
if [ "$mode" != tui ] && [ "$mode" != headless ]; then
    echo "The harness mode \"$mode\" is not one of tui, headless." >&2
    exit 78
fi
mkdir -p "$HOME/.pi/agent" "$HOME/.local/share/code-server/User" /work/sessions
# Refresh the bootstrap credential copy only when explicitly supplied by the host.
# Session refreshes subsequently belong to this workspace and survive reconnects.
if [ -f /bridge/in/auth.json ] && [ ! -f "$HOME/.pi/agent/auth.json" ]; then
    cp /bridge/in/auth.json "$HOME/.pi/agent/auth.json"
    chmod 600 "$HOME/.pi/agent/auth.json"
fi
export NODE_PATH=/usr/local/lib/node_modules/@earendil-works/pi-coding-agent/node_modules
export GRATING_DEVELOPMENT_BRIDGE=/bridge BALSAMIC_HARNESS_MODE="$mode"
# The campaign's model, named by the host; without one, the OpenAI Codex subscription.
model=(--provider "${PI_PROVIDER:-openai-codex}" --model "${PI_MODEL:-gpt-6-sol}")
thinking="${PI_THINKING-xhigh}"
if [ -n "$thinking" ]; then model+=(--thinking "$thinking"); fi
# The adapter points the harness at the balsamic-workspace MCP server and names what tmux runs: Pi's TUI with its
# extension, or the headless runner, which runs pi --mode json once per instruction and maps its stream.
node /opt/workspace/harness.mjs configure --harness "$harness" >/dev/null
command=$(node /opt/workspace/harness.mjs command --harness "$harness" --mode "$mode" -- "${model[@]}")
if ! tmux has-session -t implementation 2>/dev/null; then
    tmux new-session -d -s implementation -c /work/repo "exec $command"
fi
tmux set-option -g history-limit 100000
exec /opt/code-server/bin/code-server --bind-addr 0.0.0.0:8080 --auth none \
    --disable-telemetry --disable-update-check --disable-workspace-trust /work/repo
