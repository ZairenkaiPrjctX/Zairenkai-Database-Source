"""Deterministic JSON I/O: stable key order, LF newlines, write only when content changes."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _strip(data: Any, volatile: frozenset[str]) -> Any:
    if isinstance(data, dict):
        return {k: _strip(v, volatile) for k, v in data.items() if k not in volatile}
    if isinstance(data, list):
        return [_strip(v, volatile) for v in data]
    return data


def write_if_changed(path: Path, data: Any, volatile_keys: Iterable[str] = ()) -> bool:
    """Write `data` to `path` unless the existing content is equal.

    Keys in `volatile_keys` (e.g. "last_checked_at") are ignored for the comparison, so a run
    that only refreshes a check timestamp produces no Git diff. Returns True if written.
    """
    volatile = frozenset(volatile_keys)
    if path.exists():
        try:
            old = load(path)
        except (OSError, ValueError):
            old = None
        if old is not None and _strip(old, volatile) == _strip(data, volatile):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dumps(data))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True
