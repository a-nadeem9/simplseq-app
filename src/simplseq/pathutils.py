"""Path helpers for Linux/WSL-first SIMPLseq commands."""

from __future__ import annotations

import os
import re
from pathlib import Path


WINDOWS_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/]?(.*)$")


def user_path(value: Path | str) -> Path:
    """Return a Path, translating Windows drive paths when running in Linux/WSL."""
    text = str(value)
    match = WINDOWS_DRIVE_RE.match(text)
    if match and os.name != "nt":
        drive = match.group(1).lower()
        rest = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}").expanduser()
    return Path(text).expanduser()
