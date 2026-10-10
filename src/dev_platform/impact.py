"""Change impact and check selection. Fails closed.

Unknown impact selects every owed check; it is never read as "nothing to do".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from dev_platform.config import Check, Config
from dev_platform.model import Obligation, Stage


@cache
def _glob_re(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(path: str, patterns) -> str | None:
    for p in patterns:
        if _glob_re(p).match(path) or _glob_re(p.rstrip("/") + "/**").match(path):
            return p
    return None


@dataclass(frozen=True)
class Selected:
    check: Check
    selected: bool
    reasons: tuple[str, ...]


def select(cfg: Config, stage: Stage, changed: tuple[str, ...] | None) -> list[Selected]:
    """Decide, for every check defined at `stage`, whether it is owed and why."""
    candidates = [c for c in cfg.checks if stage in c.stages]
    reasons: dict[str, list[str]] = {c.id: [] for c in candidates}

    def owed_by_change(c: Check) -> bool:
        return c.obligation is not Obligation.PERIODIC

    if stage is Stage.FULL:
        for c in candidates:
            reasons[c.id].append("full validation runs every check")
    else:
        for c in candidates:
            if c.obligation is Obligation.ALWAYS:
                reasons[c.id].append("always-obligation")
        if changed is None:
            for c in candidates:
                if owed_by_change(c):
                    reasons[c.id].append("change set unknown: fail closed, owed")
        else:
            for path in changed:
                g = matches(path, cfg.impact_global)
                if g:
                    for c in candidates:
                        if owed_by_change(c):
                            reasons[c.id].append(f"global input {g} changed ({path})")
                    continue
                hit = False
                for c in candidates:
                    p = matches(path, c.inputs)
                    if p:
                        hit = True
                        reasons[c.id].append(f"{path} matches input {p}")
                if not hit and not matches(path, cfg.impact_ignore):
                    for c in candidates:
                        if owed_by_change(c):
                            reasons[c.id].append(f"unmapped path {path}: impact unknown, fail closed")
    out = []
    for c in candidates:
        r = tuple(dict.fromkeys(reasons[c.id]))
        out.append(Selected(c, bool(r), r or ("no changed input reaches this check",)))
    return out
