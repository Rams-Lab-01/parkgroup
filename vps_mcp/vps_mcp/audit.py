"""Append-only JSON-lines audit trail of every tool call (arguments and outcome, never output)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path: str):
        self.path = Path(os.path.expanduser(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)

    def record(self, tool: str, args: dict, *, ok: bool, duration_ms: int, note: str = "") -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "tool": tool,
            "args": {k: (v if not isinstance(v, str) or len(v) <= 500 else v[:500] + "...") for k, v in args.items()},
            "ok": ok,
            "ms": duration_ms,
            "note": note[:300],
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
