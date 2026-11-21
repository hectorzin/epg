"""Windows-safe npm invocation (npm.cmd / npx.cmd)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def npm_executable() -> str:
    if sys.platform == "win32":
        return "npm.cmd"
    return "npm"


def npx_executable() -> str:
    if sys.platform == "win32":
        return "npx.cmd"
    return "npx"


def run_npm(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [npm_executable(), *args]
    return subprocess.run(cmd, cwd=cwd, check=check)


def run_npx(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [npx_executable(), *args]
    return subprocess.run(cmd, cwd=cwd, check=check)


def npm_available() -> bool:
    return shutil.which(npm_executable()) is not None