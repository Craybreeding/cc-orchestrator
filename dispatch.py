#!/usr/bin/env python3
"""
dispatch.py — CC orchestrates Codex (review) and Kimi (code writing) as sub-agents.

Usage:
  python dispatch.py --agent kimi  --task "implement X" [--dir PATH]
  python dispatch.py --agent codex --task "review this code: ..." [--dir PATH]

Architecture:
  CC (Claude Code) = architect, task router, result synthesizer
  Kimi             = writes code   (kimi-for-coding)
  Codex            = code review   (gpt-5.3-codex / o3)
"""

import subprocess
import sys
import re
import argparse


def strip_ansi(text: str) -> str:
    return re.sub(r'\x1B[@-_][0-?]*[ -/]*[@-~]', '', text)


def clean_kimi_output(text: str) -> str:
    """Strip kimi's TUI chrome (box-drawing chars, bullet points), keep content."""
    text = strip_ansi(text)
    lines = text.split('\n')
    clean = []
    for line in lines:
        # Remove box drawing border lines entirely
        if re.match(r'^[╭╮╰╯├┤┬┴┼─│ ]+$', line):
            continue
        # Remove leading bullets and border chars
        line = re.sub(r'^[│╭╮╰╯•·▸▹→►] ?', '', line)
        line = line.strip()
        if line:
            clean.append(line)
    return '\n'.join(clean)


def clean_codex_output(text: str) -> str:
    """Extract the agent's response from codex exec stdout."""
    text = strip_ansi(text)
    # The codex response appears after the 'codex\n' label, before 'tokens used'
    match = re.search(
        r'^codex\n(.*?)(?=^tokens used|\Z)',
        text, re.MULTILINE | re.DOTALL
    )
    if match:
        return match.group(1).strip()
    # Fallback: return everything after the header separator
    parts = text.split('--------\n')
    return parts[-1].strip() if len(parts) > 1 else text.strip()


def run_kimi(task: str, workdir: str) -> str:
    """Dispatch to Kimi for code writing."""
    result = subprocess.run(
        ['kimi', '-p', task, '-y', '--no-thinking'],
        capture_output=True, text=True, timeout=180, cwd=workdir
    )
    raw = result.stdout + result.stderr
    return clean_kimi_output(raw)


def run_codex(task: str, workdir: str) -> str:
    """Dispatch to Codex for code review."""
    result = subprocess.run(
        ['codex', 'exec', '--skip-git-repo-check', task],
        capture_output=True, text=True, timeout=180, cwd=workdir
    )
    raw = result.stdout + result.stderr
    return clean_codex_output(raw)


def main():
    parser = argparse.ArgumentParser(
        description='CC sub-agent dispatcher (Kimi=write, Codex=review)'
    )
    parser.add_argument('--agent', choices=['codex', 'kimi'], required=True,
                        help='codex=review | kimi=write')
    parser.add_argument('--task', required=True,
                        help='Task description or code to act on')
    parser.add_argument('--dir', default='.',
                        help='Working directory for the agent (default: cwd)')
    args = parser.parse_args()

    print(f"[dispatch] → {args.agent} | dir={args.dir}", file=sys.stderr)
    print(f"[dispatch]   task: {args.task[:80]}{'...' if len(args.task) > 80 else ''}", file=sys.stderr)

    try:
        if args.agent == 'kimi':
            output = run_kimi(args.task, args.dir)
        else:
            output = run_codex(args.task, args.dir)
    except subprocess.TimeoutExpired:
        print(f"[dispatch] ERROR: {args.agent} timed out (180s)", file=sys.stderr)
        sys.exit(1)

    print(output)


if __name__ == '__main__':
    main()
