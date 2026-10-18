"""Parser for the Android init language (.rc). Treats the file purely as data.

Extracts services (name, binary, class, user, group, capabilities, interfaces, flags), action
triggers (including property triggers), service start/stop references, and imports.
"""

from __future__ import annotations

import shlex
from typing import Any

SECTION_KEYWORDS = {"service", "on", "import"}


def _logical_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not buf:
            start = no
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        stripped = buf.strip()
        if stripped and not stripped.startswith("#"):
            out.append((start, stripped))
        buf = ""
    return out


def _split(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=True, posix=True)
    except ValueError:
        return line.split()


def parse(text: str) -> dict[str, Any]:
    services: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    imports: list[str] = []
    current: dict[str, Any] | None = None
    for lineno, line in _logical_lines(text):
        tok = _split(line)
        if not tok:
            continue
        kw = tok[0]
        if kw == "service" and len(tok) >= 3:
            current = {
                "type": "service",
                "name": tok[1],
                "binary": tok[2],
                "args": tok[3:],
                "classes": [],
                "user": None,
                "groups": [],
                "capabilities": [],
                "interfaces": [],
                "disabled": False,
                "oneshot": False,
                "other_options": [],
                "line": lineno,
            }
            services.append(current)
        elif kw == "on" and len(tok) >= 2:
            trigger = " ".join(tok[1:])
            prop_triggers = [t.split(":", 1)[1] for t in tok[1:] if t.startswith("property:")]
            current = {
                "type": "action",
                "trigger": trigger,
                "property_triggers": prop_triggers,
                "starts": [],
                "stops": [],
                "commands": 0,
                "line": lineno,
            }
            actions.append(current)
        elif kw == "import" and len(tok) >= 2:
            imports.append(tok[1])
            current = None
        elif current is None:
            continue
        elif current["type"] == "service":
            _service_option(current, tok)
        else:
            current["commands"] += 1
            if kw in ("start", "restart", "enable") and len(tok) > 1:
                current["starts"].append(tok[1])
            elif kw == "stop" and len(tok) > 1:
                current["stops"].append(tok[1])
    for a in actions:
        a.pop("type")
    for s in services:
        s.pop("type")
    return {"services": services, "actions": actions, "imports": imports}


def _service_option(svc: dict[str, Any], tok: list[str]) -> None:
    kw, args = tok[0], tok[1:]
    if kw == "class":
        svc["classes"].extend(args)
    elif kw == "user" and args:
        svc["user"] = args[0]
    elif kw == "group":
        svc["groups"].extend(args)
    elif kw == "capabilities":
        svc["capabilities"].extend(args)
    elif kw == "interface" and len(args) >= 2:
        svc["interfaces"].append({"name": args[0], "instance": args[1]})
    elif kw == "disabled":
        svc["disabled"] = True
    elif kw == "oneshot":
        svc["oneshot"] = True
    else:
        svc["other_options"].append(kw)
