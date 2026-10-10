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
                    if ent.get("kind") == "bazel_module":
                        ok = all(ent.get(k) for k in ("name", "version")) and re.fullmatch(
                            r"[0-9a-f]{64}", str(ent.get("source_json_sha256", ""))
                        )
                        if not ok:
                            errs.append(
                                f"{w}.integrity[{j}]: bazel_module needs name, version, source_json_sha256"
                            )
                        continue
                    ok = all(ent.get(k) for k in ("name", "file", "pattern", "sha256"))
                    if not ok or not re.fullmatch(r"[0-9a-f]{64}", str(ent.get("sha256", ""))):
                        errs.append(f"{w}.integrity[{j}]: name, file, pattern, sha256(64 hex) required")
                    elif re.compile(ent["pattern"]).groups < 1:
                        errs.append(f"{w}.integrity[{j}].pattern needs a capture group")
                bsha = t.get("binary_sha256")
                if bsha is not None:
                    vals = bsha.values() if isinstance(bsha, dict) else []
                    if not vals or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in vals):
                        errs.append(f"{w}.binary_sha256: map of '<sys.platform>-<machine>' to 64 hex chars")
                    if t.get("launcher") not in tools:
                        errs.append(f"{w}.launcher: must name another tool of this profile")
            else:
                p = t.get("probe") or {}
                if not p and "closure" in t and t.get("executable"):
                    pass  # identified by closure digest alone (stronger than any version probe)
                elif not (p.get("argv") and p.get("pattern")):
                    errs.append(f"{w}: probe {{argv, pattern}} required for non-Bazel tools")
                elif re.compile(p["pattern"]).groups < 1:
                    errs.append(f"{w}.probe.pattern needs a capture group")
            if "closure" in t:
                if managed:
                    errs.append(f"{w}: closure applies to executed tools, not Bazel-managed ones")
                else:
                    errs.extend(_closure.validate(w, t["closure"]))
            for plat, src in (t.get("source") or {}).items() if isinstance(t.get("source", {}), dict) else []:
                ok = (
                    isinstance(src, dict)
                    and str(src.get("url", "")).startswith("https://")
                    and re.fullmatch(r"[0-9a-f]{64}", str(src.get("sha256", "")))
                )
                if not ok:
                    errs.append(f"{w}.source[{plat}]: https url and sha256 (64 hex) required")
            sha = t.get("sha256")
            if sha is not None:
                vals = sha.values() if isinstance(sha, dict) else [sha]
                if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in vals):
                    errs.append(f"{w}.sha256: 64 hex chars (or a map keyed by '<sys.platform>-<machine>')")
    pinned: dict[tuple[str, str, str, str], str] = {}
    for pname, prof in profiles.items():
        tools = prof.get("tools") if isinstance(prof, dict) else None
        for tname, t in (tools or {}).items():
            if not isinstance(t, dict) or not isinstance(t.get("version"), str):
                continue
            facts = [("closure", t.get("closure", {}).get("sha256")), ("source", t.get("source"))]
            for kind, mapping in facts:
                for plat, val in (mapping or {}).items() if isinstance(mapping, dict) else []:
                    key = (tname, t["version"], kind, plat)
                    enc = json.dumps(val, sort_keys=True)
                    if pinned.setdefault(key, enc) != enc:
                        errs.append(f"{pname}.{tname}@{t['version']}: conflicting {kind} pin for {plat}")
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


def _check_bazel_module(ent: dict, root: Path) -> dict:
    """A BCR module pinned by the release: the consumer declares exactly this bazel_dep version and
    the consumer's resolved graph (MODULE.bazel.lock) holds the pinned registry source.json hash."""
    proof = {"name": ent["name"], "status": "mismatch"}
    mod = root / ent.get("file", "MODULE.bazel")
    pat = rf'bazel_dep\(\s*name\s*=\s*"{re.escape(ent["name"])}"\s*,\s*version\s*=\s*"([^"]+)"'
    m = re.search(pat, mod.read_text()) if mod.is_file() else None
    if not m or m.group(1) != ent["version"]:
        proof["reason"] = f"consumer does not declare {ent['name']}@{ent['version']}"
        return proof
    lock = root / ent.get("lock_file", "MODULE.bazel.lock")
    try:
        hashes = json.loads(lock.read_text()).get("registryFileHashes", {})
    except (OSError, json.JSONDecodeError):
        proof["reason"] = "resolved graph (MODULE.bazel.lock) missing or unreadable"
        return proof
    key = f"https://bcr.bazel.build/modules/{ent['name']}/{ent['version']}/source.json"
    if hashes.get(key) != ent["source_json_sha256"]:
        proof["reason"] = "resolved graph does not hold the pinned source.json hash"
        return proof
    proof["status"] = "ok"
    return proof


def _check_integrity(ent: dict, root: Path) -> dict:
    if ent.get("kind") == "bazel_module":
        return _check_bazel_module(ent, root)
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


def _bind_launcher(entry: dict, spec: dict, verified: list[dict], root: Path) -> None:
    """The Bazel binary itself is pinned by digest and the platform enforces that pin at execution
    (BAZELISK_VERIFY_SHA256, see runtime_env). That is only meaningful if the launcher is itself
    closure-verified and the consumer does not pin a different binary; otherwise demote."""
    key = _closure.platform_key()
    want = spec["binary_sha256"].get(key)
    launcher = next((t for t in verified if t["name"] == spec["launcher"]), None)
    rc = root / ".bazeliskrc"
    declared = (
        re.search(r"BAZELISK_VERIFY_SHA256\s*=\s*([0-9a-f]{64})", rc.read_text()) if rc.is_file() else None
    )
    if declared and want and declared.group(1) != want:
        entry["status"], entry["identity"] = "mismatch", "none"
        entry["binary"] = {"status": "mismatch", "reason": ".bazeliskrc pins a different Bazel binary"}
    elif want and launcher and launcher["identity"] == "closure-verified" and launcher["status"] == "ok":
        entry["binary"] = {"status": "enforced-at-execution", "sha256": want, "launcher": spec["launcher"]}
    else:
        entry["identity"] = "bazel-declared"
        why = "no pinned Bazel binary digest for " + key if not want else "launcher is not closure-verified"
        entry["binary"] = {"status": "unbound", "reason": why}


def runtime_env(manifest: dict, profile: str) -> dict[str, str]:
    """Environment the platform adds to every check so tools enforce the release's pins themselves."""
    env: dict[str, str] = {}
    prof = manifest["profiles"].get(profile) or {"tools": {}}
    for spec in prof["tools"].values():
        pin = (spec.get("binary_sha256") or {}).get(_closure.platform_key())
        if spec.get("bazel_managed") and pin:
            env["BAZELISK_VERIFY_SHA256"] = pin
    return env


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
    # Launchers (executed tools) are verified before the Bazel-managed tools that depend on them.
    order = sorted(prof["tools"].items(), key=lambda kv: (bool(kv[1].get("bazel_managed")), kv[0]))
    for name, spec in order:
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
                    if not integ and spec.get("binary_sha256"):
                        entry["identity"] = "bazel-locked"  # pending the launcher binding below
                    if integ:
                        proofs = [_check_integrity(e, root) for e in integ]
                        entry["integrity"] = proofs
                        if all(p["status"] == "ok" for p in proofs):
                            entry["identity"] = "bazel-locked"
                        else:
                            entry["status"] = "mismatch"
                            entry["identity"] = "none"
                    if entry["identity"] == "bazel-locked" and spec.get("binary_sha256"):
                        _bind_launcher(entry, spec, tools, root)
        else:
            if "probe" in spec:
                code, out = probe(spec["probe"]["argv"])
                m = re.search(spec["probe"]["pattern"], out) if code == 0 else None
                observed = m.group(1) if m else None
            else:  # closure-only tool: present or absent; the pinned digest says which version it is
                observed = spec["version"] if _executable(spec) else None
                entry["observed_via"] = "closure"
            if observed is None:
                entry["status"] = "unavailable"
                entry["identity"] = "none"
            else:
                entry["observed"] = observed
                if not _version_ok(spec, observed):
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
                    elif entry.get("observed_via") == "closure":
                        # no probe and no pin for this platform: nothing at all was established
                        entry["status"], entry["identity"], entry["observed"] = "unavailable", "none", None
                    # otherwise unpinned/unverifiable: nothing beyond the probed version was established
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
        "platform": _closure.platform_key(),
        "scope": scope_for(tools),
        "conformant": required_ok,
        "identity_digest": digest.hexdigest(),
        # "certifiable" only when every tool was proven conformant by a strong check.
        "assurance": "certifiable" if required_ok and not weak else "diagnostic",
        "weak_tools": weak,
        "tools": tools,
    }


def scope_for(tools: list[dict]) -> dict:
    """What the environment evidence does and does not establish. Never claims hermeticity."""
    lim = [
        "tool identity is not complete execution-environment identity: the host kernel, CPU, "
        "filesystem and anything not listed above are not part of the evidence"
    ]
    if any(t.get("closure", {}).get("status") == "ok" for t in tools):
        lim.append(
            "system libraries named in closure.system_libs are trusted by name or prefix, not by content; "
            "the environment is not byte-level hermetic"
        )
    if any(t["identity"] == "bazel-locked" for t in tools):
        lim.append(
            "Bazel-managed toolchains are identified through the pinned Bazel binary digest and the "
            "resolved module graph; the Bazel repository cache, host C toolchain and network at fetch "
            "time are outside the evidence"
        )
    unverified = sorted(
        t["name"]
        for t in tools
        if t["identity"] in ("none", "version-only", "bazel-declared", "digest-verified")
    )
    if unverified:
        lim.append(f"tools without closure-level identity: {', '.join(unverified)}")
    return {"hermetic": False, "limitations": lim}


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
