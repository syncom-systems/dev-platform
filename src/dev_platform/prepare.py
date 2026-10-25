"""Prepare a project's toolchain profile: the release-specific half of `dev-platform setup`.

Everything here interprets the release's toolchain manifest (its profiles, sources, `bazel` sections), so it
belongs to the release and is run by it: `dev-platform toolchain prepare` (bootstrap contract 1, see
`dev_platform.bootstrap`). The launcher only verifies the release and runs this command; it does not need to
understand a manifest that is newer than itself. For releases that predate the contract (0.8.0 to 0.14.0) the
launcher calls `prepare` itself over the release's manifest, read from the verified snapshot and never
validated by the launcher; that adapter is frozen and applies to those releases only.

`prepare` verifies the profile's directory with the release (`toolchain verify --require-certifiable`: closure
identity against the release's manifest); provisions it (bytes only) and verifies again if that fails.
Verification is the authority: a directory is reused only when it passes. Nothing here writes into the
project (ADR 0027).
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from dev_platform.errors import EXIT_UNSATISFIED, EXIT_USAGE, DevPlatformError
from dev_platform.provision import platform_key, tool_dirs
from dev_platform.toolchain import PYTHON_TOKEN

Run = Callable[..., subprocess.CompletedProcess]


class PrepareError(DevPlatformError):
    def __init__(self, msg: str, code: int = EXIT_UNSATISFIED):
        super().__init__(msg)
        self.exit_code = code


def tail(r: subprocess.CompletedProcess, n: int = 400) -> str:
    return ((r.stdout or "") + (r.stderr or "")).strip()[-n:]


def child(*args: str, python: str | None = None) -> list[str]:
    """The pinned release's own CLI (`-P`: the working directory never shadows the snapshot)."""
    return [python or sys.executable, "-P", "-m", "dev_platform", *args]


def interpreter(manifest: dict, profile: str, dest: Path) -> str | None:
    """A profile whose python is the interpreter running the platform (`{python}`) is verified, and then used,
    by running the release on the provisioned python; other profiles run on any supported interpreter."""
    tool = manifest["profiles"][profile]["tools"].get("python") or {}
    running = tool.get("executable") == PYTHON_TOKEN or PYTHON_TOKEN in (tool.get("probe") or {}).get(
        "argv", []
    )
    exe = dest / "python" / "bin" / "python3"
    return str(exe) if running and exe.is_file() else None


def with_path(env: dict, dest: Path) -> dict:
    dirs = tool_dirs(dest) if dest.is_dir() else []
    return {**env, "PATH": os.pathsep.join([*dirs, env.get("PATH", "")])}


def first_json(text: str) -> dict:
    with contextlib.suppress(json.JSONDecodeError, IndexError):
        return json.loads(text)
    with contextlib.suppress(json.JSONDecodeError, IndexError):
        return json.loads(text.strip().splitlines()[0])
    return {}


def unsupported_tools(manifest: dict, profile: str, key: str) -> list[str]:
    """The profile's provisioned tools (those with pinned sources) that have no source for host `key`.
    Releases up to 0.10.0 skip them when provisioning, so an unsupported host would only fail verification
    later, without saying why."""
    tools = manifest["profiles"][profile]["tools"]
    return sorted(n for n, t in tools.items() if t.get("source") and key not in t["source"])


def config_problems(rec: dict) -> str:
    """The actionable conflicts of the platform-owned Bazel configuration, from an environment record."""
    cfg = next((t for t in rec.get("tools", []) if t.get("name") == "bazel-config"), None)
    if not cfg or cfg.get("status") == "ok":
        return ""
    lines = [
        f"  {c['kind']}: {c['path']}: {c['detail']} -> {c['action']}" for c in cfg["config"]["conflicts"]
    ]
    return "\nthe project's Bazel configuration conflicts with the pinned release:\n" + "\n".join(lines)


def prepare(
    manifest: dict, version: str, profile: str, project: Path, dest: Path, cenv: dict, run: Run
) -> dict:
    """The profile's directory `dest`, verified (or provisioned and verified) by the release `version` whose
    manifest this is. `cenv` is the environment of release processes (the release on its path, re-execution
    marked); `run` starts them."""
    if profile not in manifest["profiles"]:
        raise PrepareError(
            f"profile {profile!r} is not in release {version} (has {sorted(manifest['profiles'])})",
            EXIT_USAGE,
        )
    unsourced = unsupported_tools(manifest, profile, platform_key())
    if unsourced:
        sourced = [
            set(t["source"]) for t in manifest["profiles"][profile]["tools"].values() if t.get("source")
        ]
        complete = sorted(set.intersection(*sourced))  # hosts with a source for every tool of the profile
        where = f"it supports {', '.join(complete)}" if complete else "no host has a source for every tool"
        raise PrepareError(
            f"release {version} has no pinned source of {', '.join(unsourced)} (profile {profile!r}) for "
            f"this host ({platform_key()}); {where}: run on a supported host, or pin a release that supports "
            "this one"
        )
    out = {"profile": profile, "path": str(dest)}
    with tempfile.TemporaryDirectory(prefix="dev-platform-prepare-") as tmp:
        mf = Path(tmp) / "toolchains.json"  # private to this run
        mf.write_text(json.dumps(manifest))
        out |= _prepare(manifest, version, profile, project, dest, cenv, run, mf)
    return out


def _prepare(manifest, version, profile, project, dest, cenv, run, mf) -> dict:
    out: dict = {}

    def verify() -> tuple[subprocess.CompletedProcess, dict]:
        argv = ["toolchain", "verify", "--manifest", str(mf), "--profile", profile, "--require-certifiable"]
        r = run(child(*argv, python=interpreter(manifest, profile, dest)), env=with_path(cenv, dest),
                cwd=str(project))  # fmt: skip
        return r, first_json(r.stdout or "")

    def facts(rec: dict) -> dict:
        return {k: rec.get(k) for k in ("conformant", "assurance", "identity_digest")}

    if (
        "bazel" in manifest["profiles"][profile]
        and not (project / "dev-platform" / "generated.json").is_file()
    ):
        # Repository isolation (ADR 0027): preparing a profile never writes into the project. A Bazel profile
        # is verified against the platform's generated Bazel files in the project, which nothing may install,
        # so it is unsupported until the project already holds them (placed there by its owner, never here).
        raise PrepareError(
            f"profile {profile!r} needs the platform's Bazel configuration (dev-platform/) inside the "
            "repository; repository isolation forbids installing it, so this profile cannot be prepared"
        )

    if dest.is_dir():
        r, rec = verify()
        if r.returncode == 0 and rec.get("conformant"):
            return {**out, "action": "reused", **facts(rec), "python": interpreter(manifest, profile, dest)}
    argv = ["toolchain", "provision", "--pinned", "--project", str(project), "--profile", profile,
            "--dest", str(dest)]  # fmt: skip
    r = run(child(*argv), env=cenv, cwd=str(project))
    if r.returncode:
        raise PrepareError(f"release {version} could not provision {profile} in {dest}: {tail(r, 300)}")
    r, rec = verify()
    if r.returncode or not rec.get("conformant"):
        raise PrepareError(
            f"release {version} provisioned {profile} in {dest}, but it is not a conformant, certifiable "
            f"environment ({facts(rec) if rec else tail(r, 300)}){config_problems(rec)}"
        )
    return {**out, "action": "provisioned", **facts(rec), "python": interpreter(manifest, profile, dest)}
