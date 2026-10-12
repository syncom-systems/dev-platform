"""Evidence that Bazel compiles with the declared Rust toolchain, not a host installation (#111).

Declaration checks (toolchain.py) show what the consumer asked for. This shows what Bazel ran:

1. the Rustc actions of the target graph name a rustc that Bazel provides through an external
   repository (`.../external/<repo>/...`, relative to the execution root), never a host path; the
   binary resolves outside every host Rust location and reports exactly the declared version;
2. a build forced to re-execute every action (a fresh `--action_env` nonce) ran with decoy `rustc`,
   `cargo` and `rustup` first on `PATH` and as the action `PATH`; the decoys record any invocation
   and fail, so a host tool that was used cannot go unnoticed (and would fail the build).

Only Bazel and the Bazel-provided `rustc --version` are executed. Cargo is never run (Bazel-only
consumers stay Bazel-only); the decoy `cargo` is a trap, not a tool. Limit: repository rules run at
fetch time with Bazel's own environment; the action-path proof, not the decoy, covers where the
toolchain came from.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

SCHEMA = "dev-platform.bazel-rust-proof/v1"
_VERSIONS = re.compile(r"versions\s*=\s*\[([^\]]*)\]")
_EXTERNAL = re.compile(r"(^|/)external/[^/]+/")
_HOST_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/opt/homebrew/", "/opt/local/")

Run = Callable[[list[str], dict[str, str], Path], tuple[int, str, str]]


def default_run(argv: list[str], env: dict[str, str], cwd: Path) -> tuple[int, str, str]:
    cp = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    return cp.returncode, cp.stdout, cp.stderr


def declared_versions(root: Path) -> list[str]:
    f = Path(root) / "MODULE.bazel"
    if not f.is_file():
        return []
    out: list[str] = []
    for m in _VERSIONS.finditer(f.read_text()):
        out += re.findall(r'"([^"]+)"', m.group(1))
    return out


def rustc_paths(aquery_jsonproto: str) -> set[str]:
    """Every distinct rustc executable named in the Rustc actions' arguments."""
    doc = json.loads(aquery_jsonproto or "{}")
    found: set[str] = set()
    for a in doc.get("actions", []):
        if a.get("mnemonic") != "Rustc":
            continue
        for arg in a.get("arguments", []):
            if arg.endswith("/rustc") or arg == "rustc" or arg.endswith("/rustc.exe"):
                found.add(arg)
                break
    return found


def _decoys(dirpath: Path, log: Path) -> None:
    for name in ("rustc", "cargo", "rustup", "rustdoc", "clippy-driver"):
        p = dirpath / name
        p.write_text(f'#!/bin/sh\necho "$0 $*" >> "{log}"\nexit 97\n')
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def prove(
    root: Path,
    *,
    target: str | list[str] = "//...",
    bazel: str = "bazel",
    run: Run = default_run,
    base_env: dict[str, str] | None = None,
) -> dict:
    root = Path(root)
    targets = [target] if isinstance(target, str) else list(target)
    env0 = dict(base_env if base_env is not None else os.environ)
    versions = declared_versions(root)
    proof: dict = {
        "schema": SCHEMA,
        "target": targets,
        "declared_versions": versions,
        "observed": None,
        "rustc": None,
        "host_decoy": None,
        "problems": [],
        "ok": False,
    }
    problems: list[str] = proof["problems"]
    if len(versions) != 1:
        problems.append(f"cannot establish one declared Rust version from MODULE.bazel (found {versions})")
        return proof
    with tempfile.TemporaryDirectory(prefix="dp-bazel-rust-") as td:
        td_p = Path(td)
        decoy_dir, log = td_p / "decoy", td_p / "decoy.log"
        decoy_dir.mkdir()
        log.write_text("")
        _decoys(decoy_dir, log)
        path = f"{decoy_dir}:{env0.get('PATH', '/usr/bin:/bin')}"
        env = {**env0, "PATH": path}
        flags = [
            "--lockfile_mode=error",
            f"--action_env=PATH={decoy_dir}:/usr/bin:/bin",
            f"--action_env=DP_PROOF_NONCE={uuid.uuid4().hex}",
        ]
        code, _, err = run([bazel, "build", *flags, *targets], env, root)
        proof["build"] = {"exit": code}
        if code != 0:
            problems.append(
                f"bazel build failed with the decoy host tools first on PATH: {err.strip()[-300:]}"
            )
        invoked = [ln for ln in log.read_text().splitlines() if ln.strip()]
        proof["host_decoy"] = {"invoked": bool(invoked), "invocations": invoked[:5]}
        if invoked:
            problems.append("a host Rust tool was executed (decoy invoked)")
        code, out, err = run(
            [
                bazel,
                "aquery",
                *flags,
                f'mnemonic("Rustc", deps(set({" ".join(targets)})))',
                "--output=jsonproto",
            ],
            env,
            root,
        )
        paths = rustc_paths(out) if code == 0 else set()
        if code != 0 or not paths:
            problems.append(
                f"no Rustc action found for {' '.join(targets)} (aquery exit {code}): {err.strip()[-200:]}"
            )
            return proof
        code, er, err = run([bazel, "info", "execution_root"], env, root)
        exec_root = Path(er.strip()) if code == 0 and er.strip() else None
        if exec_root is None:
            problems.append("cannot determine Bazel's execution root")
            return proof
        observed: set[str] = set()
        details = []
        for rel in sorted(paths):
            external = not rel.startswith("/") and bool(_EXTERNAL.search(rel))
            real = Path(os.path.realpath(exec_root / rel)) if external else Path(rel)
            host = any(str(real).startswith(h) for h in _HOST_PREFIXES) or any(
                part in (".cargo", ".rustup") for part in real.parts
            )
            d = {
                "path": rel,
                "bazel_external_repo": external,
                "real_path": str(real),
                "sha256": None,
                "version": None,
            }
            if not external:
                problems.append(
                    f"rustc {rel} is not provided through a Bazel external repository (host installation?)"
                )
            elif host:
                problems.append(f"rustc {rel} resolves to a host location: {real}")
            elif not real.is_file():
                problems.append(f"rustc {rel} not found at {real}")
            else:
                d["sha256"] = hashlib.sha256(real.read_bytes()).hexdigest()
                code, vout, _ = run([str(real), "--version"], {"PATH": "/usr/bin:/bin"}, root)
                m = re.match(r"rustc (\d+\.\d+\.\d+\S*)", vout.strip()) if code == 0 else None
                d["version"] = m.group(1) if m else None
                if m:
                    observed.add(m.group(1))
                else:
                    problems.append(f"{rel} did not report a rustc version")
            details.append(d)
        proof["rustc"] = details
        proof["observed"] = sorted(observed)
        if observed and observed != {versions[0]}:
            problems.append(f"Bazel's rustc is {sorted(observed)}, declared {versions[0]}")
    proof["ok"] = not problems
    return proof
