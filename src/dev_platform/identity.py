"""Evidence identity and the applicability of previous evidence (R-5(i); clarifies ADR 0006 §4).

A check's identity is a digest over the components its outcome is taken to depend on. Equal digests show that
the *included* inputs are unchanged; they do not show the inputs are complete. The boundary class says how far
that goes: `declared` (configuration globs, unverified), `unknown` (nothing bounds the outcome), or `complete`
(a measuring or conservative mechanism; nothing produces it yet). Validity is not authenticity: a previous
record is caller-supplied, and matching digests in it prove nothing about where it came from.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from dev_platform.config import Check, Config
from dev_platform.impact import matches
from dev_platform.model import EvidenceState, Obligation, Outcome
from dev_platform.records import canonical_digest

ENCODING = "dev-platform.evidence-identity/1"
# Order is the order in which a stale cause is reported: the first differing component.
COMPONENTS = ("definition", "platform", "environment", "global", "inputs")
BOUNDARIES = ("complete", "declared", "unknown")
ORIGIN = "unauthenticated"


def tracked_files(root: Path) -> tuple[str, ...] | None:
    """Tracked plus untracked, not ignored, paths; None (unknown) without readable git state."""
    try:
        r = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
        )
    except (FileNotFoundError, NotADirectoryError):
        return None
    if r.returncode != 0:
        return None
    return tuple(sorted({os.fsdecode(p) for p in r.stdout.split(b"\0") if p}))


class FileDigests:
    """Per-run content digests of repository paths. A path that cannot be read makes its set unknown."""

    def __init__(self, root: Path):
        self.root, self.files, self._memo = root, tracked_files(root), {}

    def _one(self, rel: str) -> str | None:
        if rel not in self._memo:
            p = self.root / rel
            try:
                if p.is_symlink():
                    v = "symlink:" + str(p.readlink())
                elif not p.exists():
                    v = "deleted"
                else:
                    v = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                v = None  # a directory (gitlink) or unreadable file: not identifiable
            self._memo[rel] = v
        return self._memo[rel]

    def over(self, patterns: tuple[str, ...]) -> str | None:
        if self.files is None:
            return None
        entries = [(f, self._one(f)) for f in self.files if matches(f, patterns)]
        if any(d is None for _, d in entries):
            return None
        return canonical_digest(entries)

    def snapshot(self, cfg: Config) -> dict[str, dict[str, str | None]]:
        """The repository-input components of every check, read once (before any check runs)."""
        g = self.over(cfg.impact_global)
        return {c.id: {"global": g, "inputs": self.over(c.inputs)} for c in cfg.checks}


def unstable(before: dict[str, str | None], after: dict[str, str | None]) -> list[str]:
    """Components whose content differs between the pre- and post-run snapshots (or unknown after)."""
    return [k for k in ("global", "inputs") if before[k] is not None and after[k] != before[k]]


def withdraw(ident: dict, changed: list[str]) -> None:
    """Inputs changed while the run executed: the outcome is tied to no single content, so the identity
    establishes nothing reusable. The changed components become unknown."""
    for k in changed:
        ident["components"][k] = None
    ident["digest"] = None
    ident["unstable"] = changed


def boundary(c: Check) -> str:
    """No configured check is `complete`: globs are declarations, never a demonstrated read set."""
    if c.obligation is not Obligation.CHANGE or not c.inputs:
        return "unknown"  # `always`/`periodic` outcomes are not bounded by repository inputs
    return "declared"


def compute(
    cfg: Config,
    c: Check,
    files: dict[str, str | None],
    *,
    platform: dict,
    environment: dict,
    execution: dict,
    exec_env: dict[str, str] | None,
    runner: dict | None,
) -> dict:
    definition = {k: v for k, v in asdict(c).items() if k != "description"}
    if c.runner:
        definition["runner_spec"] = asdict(cfg.runners[c.runner])
    tool = environment.get("identity_digest")
    env = {
        "toolchain": tool,
        "platform": environment.get("platform"),
        "execution": {k: execution.get(k) for k in ("environment", "variables")},
        "exec_env": sorted((exec_env or {}).items()),
        "runner": {k: runner.get(k) for k in ("id", "labels")} if runner else None,
        "infra": asdict(cfg.infra) if cfg.infra else None,
    }
    components = {
        "definition": canonical_digest(definition),
        "platform": canonical_digest(platform),
        "environment": canonical_digest(env) if tool else None,
        "global": files["global"],
        "inputs": files["inputs"],
    }
    known = all(v is not None for v in components.values())
    return {
        "encoding": ENCODING,
        "boundary": boundary(c),
        "components": components,
        "digest": canonical_digest(components) if known else None,
        "unstable": [],
    }


def validate_previous(previous: object, cfg: Config) -> tuple[dict, dict[str, dict]]:
    """Structural validation of a caller-supplied record. Returns its summary and its usable entries by id."""
    problems: list[str] = []
    entries: dict[str, dict] = {}
    if not isinstance(previous, dict):
        problems.append("not a JSON object")
    else:
        if previous.get("schema") != "dev-platform.result/v1":
            problems.append(f"schema {previous.get('schema')!r} is not dev-platform.result/v1")
        name = (
            (previous.get("project") or {}).get("name") if isinstance(previous.get("project"), dict) else None
        )
        if name != cfg.project_name:
            problems.append(f"project {name!r} is not {cfg.project_name!r}")
        checks = previous.get("checks")
        if not isinstance(checks, list) or not all(isinstance(e, dict) for e in checks):
            problems.append("checks is not a list of objects")
        else:
            for e in checks:
                cid = e.get("id")
                if not isinstance(cid, str) or e.get("state") not in {s.value for s in EvidenceState}:
                    problems.append(f"check entry {cid!r} lacks a valid id or state")
                elif cid in entries:
                    problems.append(f"check {cid} is listed twice")
                else:
                    entries[cid] = e
    summary = {
        "valid": not problems,
        "problems": problems,
        "revision": previous.get("revision") if isinstance(previous, dict) else None,
        "origin": "caller-supplied, " + ORIGIN,
    }
    return summary, (entries if not problems else {})


def supported(e: dict) -> bool:
    """`verified` must be explained by the record itself: a pass in that run or a current carry it reports."""
    if e["state"] != EvidenceState.VERIFIED.value:
        return True
    reuse = e.get("reuse")
    return e.get("outcome") == Outcome.PASSED.value or (
        isinstance(reuse, dict) and reuse.get("carried") is True and reuse.get("applicability") == "current"
    )


def applicability(prev: dict | None, current: dict) -> tuple[str, str | None]:
    """(`current` | `stale` | `unknown`, cause). Unknown is uncertainty, not staleness."""
    if prev is None:
        return "unknown", "no entry in the previous record"
    if not supported(prev):
        return "unknown", "previous `verified` is not supported by a pass or a current carry in that record"
    ident = prev.get("identity")
    if not isinstance(ident, dict) or not isinstance(ident.get("components"), dict):
        return "unknown", "previous entry has no evidence identity"
    if ident.get("encoding") != ENCODING:
        return "unknown", f"identity encoding {ident.get('encoding')!r} is not {ENCODING}"
    old = ident["components"]
    for k in COMPONENTS:
        if current["components"][k] is None or not isinstance(old.get(k), str):
            return "unknown", f"identity component {k} is not computable"
    if current["boundary"] == "unknown" or ident.get("boundary") not in BOUNDARIES:
        return "unknown", "no dependency boundary bounds this check's outcome"
    for k in COMPONENTS:
        if old[k] != current["components"][k]:
            return "stale", k
    return "current", None
