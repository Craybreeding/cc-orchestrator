#!/usr/bin/env bash
# setup.sh — Install CC sub-agent MCP servers (Kimi + Codex) for Claude desktop app
# Supports: macOS, Linux  |  Windows: use WSL or run steps manually (see README)
# Usage: bash setup.sh [--install-dir DIR]
#   --install-dir  Where to permanently keep kimi_mcp_server.py (default: ~/.cc-orchestrator)

set -euo pipefail

# ── Parse args ───────────────────────────────────────────────────────────────
INSTALL_DIR="$HOME/.cc-orchestrator"
while [[ $# -gt 0 ]]; do
    case $1 in
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== CC Sub-Agent Setup ==="

# ── Detect python3 ──────────────────────────────────────────────────────────
PYTHON=""
for p in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if command -v "$p" &>/dev/null; then
        PYTHON="$(command -v "$p")"
        break
    fi
done
[ -z "$PYTHON" ] && { echo "ERROR: python3 not found. Install: https://python.org"; exit 1; }

# ── Detect Node/npm (needed for codex) ──────────────────────────────────────
if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Install Node.js first: https://nodejs.org"
    exit 1
fi

# ── Install codex if missing ────────────────────────────────────────────────
if ! command -v codex &>/dev/null && \
   ! [ -f "/opt/homebrew/bin/codex" ] && \
   ! [ -f "$HOME/.local/bin/codex" ]; then
    echo "codex not found. Installing..."
    npm install -g @openai/codex
fi

CODEX=""
for p in codex /opt/homebrew/bin/codex /usr/local/bin/codex "$HOME/.local/bin/codex"; do
    if command -v "$p" &>/dev/null || [ -f "$p" ]; then
        CODEX="$(command -v "$p" 2>/dev/null || echo "$p")"
        break
    fi
done
[ -z "$CODEX" ] && { echo "ERROR: codex still not found after install attempt"; exit 1; }

# ── Install kimi if missing ──────────────────────────────────────────────────
if ! command -v kimi &>/dev/null && \
   ! [ -f "$HOME/.local/bin/kimi" ] && \
   ! [ -f "/opt/homebrew/bin/kimi" ]; then
    echo "kimi not found. Installing..."
    $PYTHON -m pip install kimi-cli --break-system-packages 2>/dev/null \
        || $PYTHON -m pip install kimi-cli
fi

KIMI=""
for p in kimi /opt/homebrew/bin/kimi /usr/local/bin/kimi "$HOME/.local/bin/kimi"; do
    if command -v "$p" &>/dev/null || [ -f "$p" ]; then
        KIMI="$(command -v "$p" 2>/dev/null || echo "$p")"
        break
    fi
done
[ -z "$KIMI" ] && { echo "ERROR: kimi still not found after install attempt"; exit 1; }

# ── Install mcp Python package if missing ────────────────────────────────────
$PYTHON -c "import mcp" 2>/dev/null || {
    echo "mcp package not found. Installing..."
    $PYTHON -m pip install "mcp>=1.26.0" --break-system-packages 2>/dev/null \
        || $PYTHON -m pip install "mcp>=1.26.0"
}

echo "✓ python: $PYTHON"
echo "✓ codex:  $CODEX ($(${CODEX} --version 2>&1 | head -1))"
echo "✓ kimi:   $KIMI ($(${KIMI} --version 2>&1 | head -1))"

# ── Copy server to permanent install dir ─────────────────────────────────────
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/kimi_mcp_server.py" "$INSTALL_DIR/kimi_mcp_server.py"
KIMI_SERVER="$INSTALL_DIR/kimi_mcp_server.py"
echo "✓ installed server → $KIMI_SERVER"

# ── Check login status ────────────────────────────────────────────────────────
echo ""
echo "Checking login status..."
if ! $CODEX auth status &>/dev/null 2>&1; then
    echo "⚠  codex: not logged in → run: codex login"
else
    echo "✓ codex: logged in"
fi

if ! $KIMI info &>/dev/null 2>&1; then
    echo "⚠  kimi: not logged in → run: kimi login"
else
    echo "✓ kimi: logged in"
fi

# ── Detect Claude desktop config path ────────────────────────────────────────
if [[ "$(uname)" == "Darwin" ]]; then
    CLAUDE_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
else
    CLAUDE_CFG="$HOME/.config/Claude/claude_desktop_config.json"
fi
mkdir -p "$(dirname "$CLAUDE_CFG")"

# ── Backup and write config ───────────────────────────────────────────────────
[ -f "$CLAUDE_CFG" ] && cp "$CLAUDE_CFG" "${CLAUDE_CFG}.bak" && echo "✓ backed up config"

$PYTHON - <<PYEOF
import json, os

cfg_path    = """$CLAUDE_CFG"""
kimi_server = """$KIMI_SERVER"""
python_path = """$PYTHON"""
codex_path  = """$CODEX"""

cfg = {}
if os.path.exists(cfg_path):
    try:
        cfg = json.load(open(cfg_path))
    except json.JSONDecodeError:
        pass

cfg.setdefault("mcpServers", {})
cfg["mcpServers"]["codex"] = {"command": codex_path, "args": ["mcp-server"]}
cfg["mcpServers"]["kimi"]  = {"command": python_path, "args": [kimi_server]}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

print(f"✓ wrote config → {cfg_path}")
PYEOF

echo ""
echo "✅ Done! Next steps:"
echo "   1. If you saw ⚠  above, log in: codex login  /  kimi login"
echo "   2. Restart Claude desktop app"
echo "   3. Tools available: mcp__kimi__kimi_task  |  mcp__codex__codex"
