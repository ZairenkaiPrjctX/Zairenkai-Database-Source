"""Rule-based component classification driven by config/component_rules.yml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from afid.errors import ConfigError
from afid.models import CATEGORIES


@lru_cache(maxsize=4096)
def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Glob where '*' and '?' stay within a path segment and '**' spans segments."""
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(path: str, patterns: list[str]) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns)


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    subcategory: str
    paths: tuple[str, ...]
    confidence: float
    reason: str
    require_elf: bool | None = None
    soc_vendors: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()

    def matches(self, path: str, is_elf: bool | None) -> bool:
        """is_elf None means "not known yet" (remote listings): only the path decides."""
        if is_elf is not None and self.require_elf is not None and self.require_elf != is_elf:
            return False
        if self.exclude_paths and glob_match(path, list(self.exclude_paths)):
            return False
        return glob_match(path, list(self.paths))


@dataclass
class Classification:
    category: str
    subcategory: str
    confidence: float
    method: str
    rule_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    soc_vendors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "rule_ids": list(self.rule_ids),
            "confidence": round(self.confidence, 3),
            "reasons": list(self.reasons),
            "soc_vendors": sorted(self.soc_vendors),
        }


class Classifier:
    def __init__(self, rules_doc: dict[str, Any]) -> None:
        self.rules: list[Rule] = []
        seen: set[str] = set()
        for raw in rules_doc.get("rules") or []:
            try:
                rule = Rule(
                    id=raw["id"],
                    category=raw["category"],
                    subcategory=raw["subcategory"],
                    paths=tuple(raw["paths"]),
                    confidence=float(raw["confidence"]),
                    reason=raw["reason"],
                    require_elf=raw.get("require_elf"),
                    soc_vendors=tuple(raw.get("soc_vendors") or ()),
                    exclude_paths=tuple(raw.get("exclude_paths") or ()),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ConfigError(f"invalid classification rule {raw!r}: {exc}") from exc
            if rule.category not in CATEGORIES:
                raise ConfigError(f"rule {rule.id}: unknown category {rule.category}")
            if not 0 <= rule.confidence <= 1:
                raise ConfigError(f"rule {rule.id}: confidence must be within 0..1")
            if rule.id in seen:
                raise ConfigError(f"duplicate rule id {rule.id}")
            seen.add(rule.id)
            self.rules.append(rule)
        self.unknown_globs = list(rules_doc.get("catalog_unknown_globs") or [])
        self.exclude_globs = list(rules_doc.get("exclude_globs") or [])
        self.keywords = [k.lower() for k in rules_doc.get("relevance_keywords") or []]

    def classify(self, path: str, is_elf: bool) -> Classification | None:
        if self.excluded(path):
            return None
        hits = [r for r in self.rules if r.matches(path, is_elf)]
        if not hits:
            return None
        hits.sort(key=lambda r: (-r.confidence, r.id))
        best = hits[0]
        return Classification(
            category=best.category,
            subcategory=best.subcategory,
            confidence=best.confidence,
            method="rule",
            rule_ids=[r.id for r in hits],
            reasons=[f"{r.id}: {r.reason}" for r in hits],
            soc_vendors=sorted({v for r in hits for v in r.soc_vendors}),
        )

    def excluded(self, path: str) -> bool:
        return glob_match(path, self.exclude_globs)

    def best_rule(self, path: str) -> Rule | None:
        """Highest-confidence rule that could match `path` (content not known yet)."""
        if self.excluded(path):
            return None
        hits = [r for r in self.rules if r.matches(path, None)]
        return min(hits, key=lambda r: (-r.confidence, r.id)) if hits else None

    def candidate(self, path: str) -> bool:
        """Could this path become a catalog component once its content is known? Used to
        select files from remote dump listings before anything is fetched."""
        if self.excluded(path):
            return False
        return any(r.matches(path, None) for r in self.rules) or self.catalog_unknown(path)

    def catalog_unknown(self, path: str) -> bool:
        return not self.excluded(path) and glob_match(path, self.unknown_globs)

    def relevant(self, *texts: str) -> bool:
        joined = " ".join(texts).lower()
        return any(k in joined for k in self.keywords)
