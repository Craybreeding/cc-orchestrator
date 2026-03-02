import asyncio
import re
import shutil

from mcp.server.fastmcp import FastMCP

import os
from pathlib import Path

_KIMI_CANDIDATES = [
    shutil.which("kimi"),
    str(Path.home() / ".local/bin/kimi"),
    "/opt/homebrew/bin/kimi",
    "/usr/local/bin/kimi",
]
KIMI_PATH = next((p for p in _KIMI_CANDIDATES if p and os.path.isfile(p)), None)
if KIMI_PATH is None:
    raise FileNotFoundError("kimi not found. Tried: " + str(_KIMI_CANDIDATES))

mcp_server = FastMCP("kimi-agent")


def _clean_output(text: str) -> str:
    """Strip ANSI codes and box-drawing characters."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"[╭╮╰╯│•]", "", text)
    return text


@mcp_server.tool()
async def kimi_task(task: str, workdir: str = ".") -> str:
    """Dispatch coding task to Kimi (kimi-for-coding). Returns code/output."""
    proc = await asyncio.create_subprocess_exec(
        KIMI_PATH, "-p", task, "-y", "--no-thinking",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workdir,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("kimi_task timed out after 180 seconds")
    if proc.returncode != 0:
        output = (stdout.decode("utf-8", errors="replace") +
                  stderr.decode("utf-8", errors="replace"))
        raise RuntimeError(f"kimi_task failed with return code {proc.returncode}: {output[:200]}")
    output = (stdout.decode("utf-8", errors="replace") +
              stderr.decode("utf-8", errors="replace"))
    return _clean_output(output)


if __name__ == "__main__":
    mcp_server.run(transport="stdio")
