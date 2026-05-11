"""Structured progress event helpers for SIMPLseq runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def emit_event(
    path: Path,
    stage: str,
    status: str,
    *,
    message: str = "",
    user_visible: bool = True,
    extra: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event: dict[str, Any] = {
        "time": utc_now(),
        "stage": stage,
        "status": status,
        "user_visible": user_visible,
    }
    if message:
        event["message"] = message
    if extra:
        event.update(extra)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a SIMPLseq progress event.")
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("--file", required=True)
    emit.add_argument("--stage", required=True)
    emit.add_argument("--status", required=True)
    emit.add_argument("--message", default="")
    emit.add_argument("--hidden", action="store_true")
    args = parser.parse_args()
    if args.command == "emit":
        emit_event(
            Path(args.file),
            args.stage,
            args.status,
            message=args.message,
            user_visible=not args.hidden,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
