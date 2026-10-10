"""Toolchain manifests (dev-platform.toolchains/v1) and environment verification.

A platform release carries one manifest of named profiles. A consumer selects a profile; the
platform proves the environment matches it and records the identity. Bazel-managed toolchains are
never executed or replaced here: their *declarations* in the consumer are reconciled against the
manifest.
"""

from __future__ import annotations

import hashlib
import json
import platform as _platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from dev_platform.errors import ConfigError

SCHEMA = "dev-platform.toolchains/v1"
PYTHON_TOKEN = "{python}"  # noqa: S105 - placeholder, not a credential
Probe = Callable[[list[str]], tuple[int, str]]


def validate(doc: dict) -> dict:
    errs: list[str] = []
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA!r}")
    profiles = doc.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        errs.append("profiles: at least one profile is required")
        profiles = {}
    for pname, prof in profiles.items():
        tools = prof.get("tools") if isinstance(prof, dict) else None
        if not isinstance(tools, dict) or not tools:
            errs.append(f"profile {pname}: tools required")
            continue
        for tname, t in tools.items():
            w = f"profile {pname}.{tname}"
            if not isinstance(t, dict) or not isinstance(t.get("version"), str) or not t["version"]:
                errs.append(f"{w}: exact version required")
                continue
            if t.get("compare", "exact") not in ("exact", "prefix"):
                errs.append(f"{w}.compare: exact|prefix")
            managed = t.get("bazel_managed", False)
            if managed:
                d = t.get("declared_in") or {}
                if not (d.get("file") and d.get("pattern")):
                    errs.append(f"{w}: bazel_managed tools need declared_in {{file, pattern}}")
                elif re.compile(d["pattern"]).groups < 1:
                    errs.append(f"{w}.declared_in.pattern needs a capture group")
            else:
                p = t.get("probe") or {}
                if not (p.get("argv") and p.get("pattern")):
                    errs.append(f"{w}: probe {{argv, pattern}} required for non-Bazel tools")
                elif re.compile(p["pattern"]).groups < 1:
                    errs.append(f"{w}.probe.pattern needs a capture group")
            sha = t.get("sha256")
            if sha is not None:
                vals = sha.values() if isinstance(sha, dict) else [sha]
                if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in vals):
                    errs.append(f"{w}.sha256: 64 hex chars (or a map keyed by '<sys.platform>-<machine>')")
    if errs:
        raise ConfigError([f"toolchain manifest: {e}" for e in errs])
    return doc


def default_probe(argv: list[str]) -> tuple[int, str]:
    argv = [sys.executable if a == PYTHON_TOKEN else a for a in argv]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 127, ""
    return r.returncode, r.stdout + r.stderr


def _version_ok(spec: dict, observed: str) -> bool:
    if spec.get("compare", "exact") == "prefix":
        return observed.startswith(spec["version"])
    return observed == spec["version"]


def _binary_digest(argv0: str) -> str | None:
    path = sys.executable if argv0 == PYTHON_TOKEN else shutil.which(argv0)
    if not path:
        return None
    return hashlib.sha256(Path(path).resolve().read_bytes()).hexdigest()


def _expected_sha(spec: dict) -> str | None:
    sha = spec.get("sha256")
    if isinstance(sha, dict):
        return sha.get(f"{sys.platform}-{_platform.machine()}")
    return sha


def verify_profile(manifest: dict, profile: str, root: Path, probe: Probe = default_probe) -> dict:
    """Return an environment record. conformant only if every required tool is proven."""
    prof = manifest["profiles"].get(profile)
    if prof is None:
        raise ConfigError(
            [
                f"profile {profile!r} is not defined by this platform release "
                f"(available: {sorted(manifest['profiles'])})"
            ]
        )
    tools = []
    for name, spec in sorted(prof["tools"].items()):
        entry = {
            "name": name,
            "expected": spec["version"],
            "observed": None,
            "identity": "version-only",
            "status": "ok",
        }
        if spec.get("bazel_managed"):
            d = spec["declared_in"]
            entry["identity"] = "bazel-reconciled"
            f = root / d["file"]
            m = re.search(d["pattern"], f.read_text()) if f.is_file() else None
            if not m:
                entry["status"] = "unreconciled"
            else:
                entry["observed"] = m.group(1)
                entry["status"] = "ok" if _version_ok(spec, m.group(1)) else "mismatch"
        else:
            code, out = probe(spec["probe"]["argv"])
            m = re.search(spec["probe"]["pattern"], out) if code == 0 else None
            if not m:
                entry["status"] = "unavailable"
            else:
                entry["observed"] = m.group(1)
                if not _version_ok(spec, m.group(1)):
                    entry["status"] = "mismatch"
                want = _expected_sha(spec)
                if want:
                    entry["identity"] = "digest-verified"
                    if _binary_digest(spec["probe"]["argv"][0]) != want:
                        entry["status"] = "mismatch"
        tools.append(entry)
    required_ok = all(t["status"] == "ok" for t in tools)
    identity = {
        "profile": profile,
        "tools": [{"name": t["name"], "observed": t["observed"], "identity": t["identity"]} for t in tools],
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    return {
        "profile": profile,
        "conformant": required_ok,
        "identity_digest": digest.hexdigest(),
        "tools": tools,
    }
