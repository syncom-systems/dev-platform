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

from dev_platform import closure as _closure
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
                for j, ent in enumerate(t.get("integrity", [])):
                    ok = all(ent.get(k) for k in ("name", "file", "pattern", "sha256"))
                    if not ok or not re.fullmatch(r"[0-9a-f]{64}", str(ent.get("sha256", ""))):
                        errs.append(f"{w}.integrity[{j}]: name, file, pattern, sha256(64 hex) required")
                    elif re.compile(ent["pattern"]).groups < 1:
                        errs.append(f"{w}.integrity[{j}].pattern needs a capture group")
            else:
                p = t.get("probe") or {}
                if not (p.get("argv") and p.get("pattern")):
                    errs.append(f"{w}: probe {{argv, pattern}} required for non-Bazel tools")
                elif re.compile(p["pattern"]).groups < 1:
                    errs.append(f"{w}.probe.pattern needs a capture group")
            if "closure" in t:
                if managed:
                    errs.append(f"{w}: closure applies to executed tools, not Bazel-managed ones")
                else:
                    errs.extend(_closure.validate(w, t["closure"]))
            sha = t.get("sha256")
            if sha is not None:
                vals = sha.values() if isinstance(sha, dict) else [sha]
                if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in vals):
                    errs.append(f"{w}.sha256: 64 hex chars (or a map keyed by '<sys.platform>-<machine>')")
    if errs:
        raise ConfigError([f"toolchain manifest: {e}" for e in errs])
    return doc


# What the verification actually established, weakest to strongest. A tool's strength is assigned
# only by the code path that performed the corresponding check; it is never read from the manifest.
# digest-verified: the executable's own bytes only. closure-verified: the whole runtime closure
# (see closure.py). Only closure-verified and bazel-locked can certify.
STRENGTH = {
    "none": 0,
    "version-only": 1,
    "bazel-declared": 1,
    "digest-verified": 1,
    "closure-verified": 2,
    "bazel-locked": 2,
}
CERTIFIABLE_STRENGTH = 2


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


def _executable(spec: dict) -> str | None:
    argv0 = spec.get("executable") or spec["probe"]["argv"][0]
    return sys.executable if argv0 == PYTHON_TOKEN else shutil.which(argv0)


def _binary_digest(argv0: str) -> str | None:
    path = sys.executable if argv0 == PYTHON_TOKEN else shutil.which(argv0)
    if not path:
        return None
    return hashlib.sha256(Path(path).resolve().read_bytes()).hexdigest()


def _verify_closure(spec: dict, linkage) -> dict:
    """Outcome of the closure checks: {'status': ok|mismatch|unpinned|unverifiable, ...}."""
    c = spec["closure"]
    key = _closure.platform_key()
    want = c["sha256"].get(key)
    if want is None:
        return {"status": "unpinned", "reason": f"no closure digest pinned for {key}"}
    root = _closure.resolve_root(c, _executable(spec))
    if root is None:
        return {"status": "unverifiable", "reason": "executable not found"}
    try:
        got, files = _closure.digest(root)
    except (ConfigError, OSError) as e:
        return {"status": "mismatch", "reason": str(e)}
    out = {"kind": c["kind"], "root": str(root), "platform": key, "digest": got, "files": files}
    if got != want:
        return {**out, "status": "mismatch", "reason": f"closure digest {got} != pinned {want}"}
    link = _closure.check_linkage(root, c["system_libs"], linkage)
    out["linkage"] = link
    if link["violations"] or link["unknown"]:
        return {**out, "status": "mismatch", "reason": "native objects link outside the closure"}
    out["status"] = "ok"
    out["scope"] = (
        "closure bytes pinned; native dependencies limited to the closure and declared system "
        "libraries, which are trusted by name, not by content"
    )
    return out


def _expected_sha(spec: dict) -> str | None:
    sha = spec.get("sha256")
    if isinstance(sha, dict):
        return sha.get(f"{sys.platform}-{_platform.machine()}")
    return sha


def _check_integrity(ent: dict, root: Path) -> dict:
    """Pinned toolchain input: the consumer's declaration must carry the pinned sha256, and the
    consumer's resolved graph (lock file) must contain it too."""
    proof = {"name": ent["name"], "status": "mismatch"}
    f = root / ent["file"]
    m = re.search(ent["pattern"], f.read_text()) if f.is_file() else None
    if not m or m.group(1) != ent["sha256"]:
        proof["reason"] = "declared integrity differs from the release's pinned value"
        return proof
    lock = ent.get("lock_file")
    if lock:
        lf = root / lock
        if not lf.is_file() or ent["sha256"] not in lf.read_text():
            proof["reason"] = f"pinned digest not present in resolved graph {lock}"
            return proof
    proof["status"] = "ok"
    return proof


def verify_profile(
    manifest: dict,
    profile: str,
    root: Path,
    probe: Probe = default_probe,
    linkage=_closure.default_linkage,
) -> dict:
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
            entry["identity"] = "none"
            f = root / d["file"]
            m = re.search(d["pattern"], f.read_text()) if f.is_file() else None
            if not m:
                entry["status"] = "unreconciled"
            else:
                entry["observed"] = m.group(1)
                if not _version_ok(spec, m.group(1)):
                    entry["status"] = "mismatch"
                else:
                    entry["identity"] = "bazel-declared"
                    integ = spec.get("integrity", [])
                    if integ:
                        proofs = [_check_integrity(e, root) for e in integ]
                        entry["integrity"] = proofs
                        if all(p["status"] == "ok" for p in proofs):
                            entry["identity"] = "bazel-locked"
                        else:
                            entry["status"] = "mismatch"
                            entry["identity"] = "none"
        else:
            code, out = probe(spec["probe"]["argv"])
            m = re.search(spec["probe"]["pattern"], out) if code == 0 else None
            if not m:
                entry["status"] = "unavailable"
                entry["identity"] = "none"
            else:
                entry["observed"] = m.group(1)
                if not _version_ok(spec, m.group(1)):
                    entry["status"] = "mismatch"
                if entry["status"] != "ok":
                    entry["identity"] = "none"
                elif "closure" in spec:
                    proof = _verify_closure(spec, linkage)
                    entry["closure"] = proof
                    if proof["status"] == "ok":
                        entry["identity"] = "closure-verified"
                    elif proof["status"] == "mismatch":
                        entry["status"] = "mismatch"
                        entry["identity"] = "none"
                    # unpinned/unverifiable: nothing beyond the version was established
                elif _expected_sha(spec):
                    if _binary_digest(spec["probe"]["argv"][0]) == _expected_sha(spec):
                        entry["identity"] = "digest-verified"
                    else:
                        entry["status"] = "mismatch"
                        entry["identity"] = "none"
        tools.append(entry)
    required_ok = all(t["status"] == "ok" for t in tools)
    weak = [t["name"] for t in tools if STRENGTH[t["identity"]] < CERTIFIABLE_STRENGTH]
    identity = {
        "profile": profile,
        "tools": [{"name": t["name"], "observed": t["observed"], "identity": t["identity"]} for t in tools],
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    return {
        "profile": profile,
        "conformant": required_ok,
        "identity_digest": digest.hexdigest(),
        # "certifiable" only when every tool was proven conformant by a strong check.
        "assurance": "certifiable" if required_ok and not weak else "diagnostic",
        "weak_tools": weak,
        "tools": tools,
    }


def measure(manifest: dict, profile: str, linkage=_closure.default_linkage) -> dict:
    """Measure the closures of the tools as installed here, to author the manifest's pinned digests.

    This only reports; pinning a measured value is a reviewed change to the manifest, never
    something the verifier does on its own.
    """
    prof = manifest["profiles"].get(profile)
    if prof is None:
        raise ConfigError([f"profile {profile!r} is not defined"])
    out = {}
    for name, spec in sorted(prof["tools"].items()):
        c = spec.get("closure")
        if not c:
            continue
        root = _closure.resolve_root(c, _executable(spec))
        if root is None:
            out[name] = {"error": "executable not found"}
            continue
        d, files = _closure.digest(root)
        deps = set()
        for obj in _closure.native_objects(root):
            deps.update(linkage(obj) or ["<unlistable>"])
        out[name] = {
            "platform": _closure.platform_key(),
            "root": str(root),
            "sha256": d,
            "files": files,
            "external_dependencies": sorted(deps),
        }
    return out
