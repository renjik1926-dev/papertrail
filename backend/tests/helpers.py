"""Top-level functions the child-process tests can import under "spawn"."""

from __future__ import annotations

import time
from typing import Any


def slow_parse(path: str, max_pages: int) -> dict[str, Any]:
    time.sleep(30)
    return {"status": "failed", "reason": "parse_error"}
