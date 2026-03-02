# cc-orchestrator

> Let Claude Code orchestrate **Kimi** (write code) and **Codex** (review code) as sub-agents via MCP.

## Why

Claude Code is great at architecture and decision-making, but burns your Claude quota on code generation too. This package wires up Kimi and Codex as MCP tools so CC delegates the heavy lifting — saving 50–70% of Claude token usage on code-heavy tasks.

## Architecture

```
You
 └── Claude Code (CC)          ← architect, task router, result synthesizer
       ├── mcp__kimi__kimi_task    ← Kimi (kimi-for-coding)  writes code
       └── mcp__codex__codex       ← Codex (gpt-5.3-codex)   reviews code
```

**Flow:**
```
1. You give CC a task
2. CC breaks it down
3. CC dispatches coding subtasks → Kimi writes files
4. CC dispatches review          → Codex finds bugs
5. CC synthesizes, decides next step
6. Repeat until done
```

**Token cost per task:**
```
Claude (CC)  = architecture + routing + synthesis  [small]
Kimi         = code generation                     [Moonshot quota]
Codex        = code review                         [OpenAI quota]
```

## Requirements

| Tool | Install |
|------|---------|
| [Node.js + npm](https://nodejs.org) | Required for Codex CLI |
| [Codex CLI](https://github.com/openai/codex) | `npm install -g @openai/codex` |
| [Kimi CLI](https://moonshotai.github.io/kimi-cli/) | `pip install kimi-cli` |
| Python 3 + mcp | `pip install "mcp>=1.26.0"` |
| Claude desktop app | [claude.ai/download](https://claude.ai/download) |

> macOS and Linux supported. Windows: use WSL.

## Install

```bash
git clone https://github.com/Craybreeding/cc-orchestrator
cd cc-orchestrator
bash setup.sh
```

`setup.sh` will:
- Auto-detect or install Codex / Kimi / mcp
- Copy `kimi_mcp_server.py` to `~/.cc-orchestrator/` (permanent location)
- Write MCP config into Claude desktop app
- Warn if Codex or Kimi are not logged in

Custom install path:
```bash
bash setup.sh --install-dir ~/my-tools
```

## After Install

```bash
# If prompted, log in:
codex login
kimi login

# Then restart Claude desktop app
```

## Verify

In Claude Code, say:
> Use kimi_task to write a Python function that adds two numbers

If it returns code — you're connected.

## Files

| File | Purpose |
|------|---------|
| `kimi_mcp_server.py` | FastMCP stdio server wrapping `kimi -p` |
| `setup.sh` | One-shot installer (macOS/Linux) |
| `dispatch.py` | Fallback: subprocess mode (no MCP needed) |

## Uninstall

Remove the `codex` and `kimi` entries from:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

Then restart Claude desktop app.
