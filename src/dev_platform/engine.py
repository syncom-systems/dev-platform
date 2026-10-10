"""Plan, execute and record a verification run (result schema dev-platform.result/v1)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from dev_platform import __version__
from dev_platform.adapters import PYTHON, Command, command_for
from dev_platform.config import Config
from dev_platform.impact import select
from dev_platform.model import ADMISSION_STAGES, EvidenceState, Outcome, Stage, advance
from dev_platform.resolve import Resolution
from dev_platform.runners import Route, load_profile, route

RESULT_SCHEMA = "dev-platform.result/v1"
Executor = Callable[[Command, Path], int]


def subprocess_executor(cmd: Command, cwd: Path) -> int:
    argv = [sys.executable if a == PYTHON else a for a in cmd.argv]
    try:
        env = {**os.environ, **dict(cmd.env)}
        return subprocess.run(argv, cwd=cwd, env=env, stdout=sys.stderr, stdin=subprocess.DEVNULL).returncode
    except FileNotFoundError:
        return 127


def git_revision(root: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_dirty(root: Path) -> bool:
    """True when the tree differs from HEAD (or git state is unreadable: fail closed)."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return True
    return r.returncode != 0 or bool(r.stdout.strip())


def git_changed(root: Path, *, base: str | None = None, staged: bool = False) -> tuple[str, ...] | None:
    """Changed paths from git, or None (unknown) on any failure."""

    def run(*args: str) -> list[str] | None:
        try:
            r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
        except FileNotFoundError:
            return None
        return r.stdout.splitlines() if r.returncode == 0 else None

    if staged:
        out = run("diff", "--cached", "--name-only", "--no-renames")
        return tuple(sorted(out)) if out is not None else None
    if base:
        mb = run("merge-base", base, "HEAD")
        tracked = run("diff", "--name-only", "--no-renames", mb[0]) if mb else None
        untracked = run("ls-files", "--others", "--exclude-standard")
        if tracked is None or untracked is None:
            return None
        return tuple(sorted(set(tracked) | set(untracked)))
    return None


def _release_identity(res: Resolution) -> dict:
    rel = res.release or {}
    return {
        "version": res.version,
        "tree_digest": res.digest,
        "source_digest": (rel.get("platform") or {}).get("source_digest"),
        "sbom_sha256": (rel.get("sbom") or {}).get("sha256"),
        "synthesized": bool(rel.get("synthesized")),
    }


def build(
    cfg: Config,
    root: Path,
    resolution: Resolution,
    stage: Stage,
    changed: tuple[str, ...] | None,
    *,
    execute: bool,
    executor: Executor = subprocess_executor,
    previous: dict | None = None,
    infra_profile: Path | None = None,
    event_trust: str = "untrusted",
    revision: str | None = None,
    dirty: bool = False,
    environment: dict | None = None,
    exec_env: dict[str, str] | None = None,
) -> dict:
    prev_state = {c["id"]: EvidenceState(c["state"]) for c in (previous or {}).get("checks", [])}
    offered = load_profile(infra_profile)
    selection = {s.check.id: s for s in select(cfg, stage, changed)}

    checks, regressions = [], []
    for c in cfg.checks:
        s = selection.get(c.id)
        entry: dict = {
            "id": c.id,
            "adapter": c.adapter,
            "obligation": c.obligation.value,
            "cost": c.cost.value,
        }
        if s is None:
            outcome, impacted = Outcome.NOT_RUN, False
            entry |= {"selected": False, "reasons": [f"not defined for stage {stage.value}"]}
        else:
            impacted = s.selected
            entry |= {"selected": s.selected, "reasons": list(s.reasons)}
            outcome = Outcome.NOT_RUN
        if c.runner:
            r: Route = route(cfg.runners[c.runner], offered, event_trust)
            entry["runner"] = {
                "requirement": c.runner,
                "routed": r.ok,
                "id": r.runner_id,
                "labels": list(r.labels),
                "reason": r.reason,
            }
        if s is not None and s.selected:
            cmd = command_for(c, root)
            if exec_env:
                cmd = Command(cmd.argv, (*cmd.env, *sorted(exec_env.items())))
            entry["command"] = list(cmd.argv)
            if execute:
                if entry.get("runner") and not entry["runner"]["routed"]:
                    outcome = Outcome.UNAVAILABLE
                    entry["exit_code"] = None
                else:
                    code = executor(cmd, root)
                    entry["exit_code"] = code
                    outcome = (
                        Outcome.PASSED
                        if code == 0
                        else Outcome.UNAVAILABLE
                        if code == 127
                        else Outcome.FAILED
                    )
            else:
                outcome = Outcome.NOT_RUN
        before = prev_state.get(c.id)
        after = advance(before, impacted=impacted, outcome=outcome)
        if before is EvidenceState.VERIFIED and after is EvidenceState.FAILED:
            regressions.append(c.id)
        entry |= {"outcome": outcome.value, "state": after.value}
        checks.append(entry)

    env_rec = environment or {"profile": None, "conformant": None, "tools": []}
    owed = [e for e in checks if e["selected"]]
    unsatisfied = [e["id"] for e in owed if e["outcome"] != Outcome.PASSED.value]
    # A non-conformant environment makes every admission claim false (no silent substitution).
    if env_rec["conformant"] is False and stage in ADMISSION_STAGES and execute:
        unsatisfied.append("environment")
    admission = None
    if stage in ADMISSION_STAGES:
        admission = "admitted" if execute and not unsatisfied else "blocked"

    blockers = []
    if stage is not Stage.FULL:
        blockers.append("certification requires the full stage")
    if not resolution.certifiable:
        blockers.append(f"platform mode '{resolution.mode}' is not certifiable")
    if revision is None:
        blockers.append("revision unknown (not a git checkout)")
    if env_rec["conformant"] is not True:
        blockers.append("environment does not conform to a platform toolchain profile")
    if env_rec.get("conformant") and env_rec.get("assurance") != "certifiable":
        blockers.append(
            "tool identity too weak for certification (version-level only): "
            + ", ".join(env_rec.get("weak_tools", []))
        )
    if dirty:
        blockers.append("working tree has uncommitted changes")
    if not execute:
        blockers.append("dry run")
    blockers += [f"check {e['id']} is {e['state']}" for e in checks if e["state"] != "verified"]
    certified = not blockers

    return {
        "schema": RESULT_SCHEMA,
        "platform": {
            "running_version": __version__,
            "mode": resolution.mode,
            "pinned_version": resolution.version,
            "digest": resolution.digest,
        },
        "project": {"name": cfg.project_name, "assurance": cfg.assurance, "bazel_only": cfg.bazel_only},
        "revision": revision,
        "stage": stage.value,
        "environment": {"release": _release_identity(resolution), **env_rec},
        "change_set": {"known": changed is not None, "paths": list(changed) if changed else []},
        "executed": execute,
        "checks": checks,
        "unsatisfied_obligations": unsatisfied,
        "regressions": regressions,
        "admission": admission,
        "certification": {"certified": certified, "release_eligible": certified, "blockers": blockers},
        "exit": 1 if (execute and unsatisfied) else 0,
    }
