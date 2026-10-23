#!/usr/bin/env python3
"""Qualify a toolchain profile by REAL execution.

A profile is only claimed supported when this passes on the platforms it claims: it builds and
installs a release from this checkout (the operator code path), runs the real build system and
compiler on a real fixture under that profile at the `full` stage on a clean git tree, and requires
a certified result. No tool is emulated. Synthetic consumer tests (tests/test_compat.py) exercise
the adoption contract only and are NOT evidence of qualification.

    python tools/qualify.py --fixture fixtures-real/rust-bazel --profile rust-bazel --out qual.json

Environment: the profile's tools must already be realized and on PATH (tools/setup_env.py).
Exit status 0 only when the result is certified.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".devenv" / "qualify"


def rmtree(path: Path) -> None:
    """Remove a tree that may contain read-only (frozen) directories."""
    for dirpath, dirnames, _ in os.walk(path):
        for d in dirnames:
            os.chmod(Path(dirpath) / d, 0o700)
    if path.exists():
        os.chmod(path, 0o700)
    shutil.rmtree(path, ignore_errors=True)


def run(argv, cwd, env, check=True):
    r = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True)
    if check and r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(map(str, argv))}")
    return r


def make_store(env: dict, store: Path) -> str:
    m = re.search(r'^__version__ = "([^"]+)"', (ROOT / "src/dev_platform/__init__.py").read_text(), re.M)
    assert m
    version = m.group(1)
    out = WORK / "release"
    for d in (out, store):
        rmtree(d)
    py = [sys.executable, "-m", "dev_platform"]
    run(
        [*py, "release", "build", "--version", version, "--out", str(out), "--src", str(ROOT / "src")],
        ROOT,
        env,
    )
    arc = WORK / "release.tar.gz"
    packed = run([*py, "release", "pack", str(out / version), "--out", str(arc)], ROOT, env).stdout
    m = re.search(r"sha256 = (\w+)", packed)
    assert m
    sha = m.group(1)
    run([*py, "release", "install", str(arc), "--archive-sha256", sha, "--store", str(store)], ROOT, env)
    return version


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{path}: {old!r} not found"
    path.write_text(text.replace(old, new, 1))


def _lock_tamper_of(module: str):
    def tamper(c: Path) -> None:
        lock = json.loads((c / "MODULE.bazel.lock").read_text())
        hit = [k for k in lock["registryFileHashes"] if f"/{module}/" in k and k.endswith("source.json")]
        assert hit, f"{module} is not in the resolved graph"
        for k in hit:
            lock["registryFileHashes"][k] = "0" * 64
        (c / "MODULE.bazel.lock").write_text(json.dumps(lock, indent=2))

    return tamper


_lock_tamper = _lock_tamper_of("rules_rust")


def _bazel_cases(other_bazel: str, rust: str, other_rust: str, dep: str, dep_version: str) -> list:
    """`dep` must NOT already be in the resolved graph (rules_rust 0.74 already pulls abseil-cpp)."""
    return [
        ("resolved graph tampered", _lock_tamper, "environment"),
        ("undeclared module change (lockfile_mode=error)", lambda c: _sub(c / "MODULE.bazel", 'module(name = "rust_demo", version = "0.1.0")', 'module(name = "rust_demo", version = "0.1.0")\nbazel_dep(name = "' + dep + '", version = "' + dep_version + '")'), "check"),
        ("declared bazel version differs", lambda c: (c / ".bazelversion").write_text(other_bazel + "\n"), "environment"),
        ("declared rust version differs", lambda c: _sub(c / "MODULE.bazel", rust, other_rust), "environment"),
        ("failing test", lambda c: _sub(c / "src/lib.rs", "assert_eq!(super::add(2, 3), 5)", "assert_eq!(super::add(2, 3), 6)"), "check"),
    ]  # fmt: skip


# profile -> [(name, mutation, what must be true afterwards)]. Each must end NOT certified.
NEGATIVE = {
    "rust-bazel": None,  # built by _bazel_cases below
    "rust-cargo": [
        ("failing test", lambda c: _sub(c / "src/lib.rs", "assert_eq!(super::add(2, 3), 5)", "assert_eq!(super::add(2, 3), 6)"), "check"),
        ("lock file out of date (--locked)", lambda c: _sub(c / "Cargo.toml", 'edition = "2021"', 'edition = "2021"\n\n[dependencies]\nsmallvec = "1"'), "check"),
    ],
    "rust-cargo-1.99": None,  # same cases as rust-cargo, set below
    "python": [
        ("failing test", lambda c: _sub(c / "app.py", "a + b", "a - b"), "check"),
    ],
}  # fmt: skip


def _append(path_in_consumer: str, text: str):
    def mutate(c: Path) -> None:
        with open(c / path_in_consumer, "a") as f:
            f.write(text)

    return mutate


def _write(path_in_consumer: str, text: str):
    def mutate(c: Path) -> None:
        (c / path_in_consumer).write_text(text)

    return mutate


def _baseline_cases(rust: bool, python: bool) -> list:
    """Platform-owned Bazel configuration (bazelconf.py): each independent or edited setting must fail
    conformance (`environment`); a failing test or a lint finding must fail a check."""
    cases = [
        ("generated file edited by hand", _append("dev-platform/bazel.bazelrc", "\nbuild --jobs=1\n"), "environment"),
        ("declared bazel version differs", _write(".bazelversion", "9.2.0\n"), "environment"),
    ]  # fmt: skip
    if rust:
        cases += [
            ("resolved graph tampered (rules_rust)", _lock_tamper_of("rules_rust"), "environment"),
            ("second Rust toolchain declared", _append("MODULE.bazel", 'bazel_dep(name = "rules_rust", version = "0.60.0")\n'), "environment"),
            ("compiler pinned outside the platform", _write("rust-toolchain.toml", '[toolchain]\nchannel = "1.80.0"\n'), "environment"),
            ("independent formatter policy", _write("rustfmt.toml", "max_width = 60\n"), "environment"),
            ("failing Rust test", lambda c: _sub(c / "rs/src/lib.rs", "assert_eq!(super::add(2, 3), 5)", "assert_eq!(super::add(2, 3), 6)"), "check"),
            ("Rust lint finding", _append("rs/src/lib.rs", "pub fn lint(a: i32) -> i32 {\n    return a;\n}\n"), "check"),
            ("Rust formatting finding", _append("rs/src/lib.rs", "pub fn ugly( a:i32 )->i32{a}\n"), "check"),
        ]  # fmt: skip
    if python:
        cases += [
            ("resolved graph tampered (rules_python)", _lock_tamper_of("rules_python"), "environment"),
            ("independent Python version", _append(".bazelrc", "\nbuild --@rules_python//python/config_settings:python_version=3.11\n"), "environment"),
            ("independent linter policy", _write("ruff.toml", "line-length = 60\n"), "environment"),
            ("independent type-checker policy", _write("pyproject.toml", "[tool.mypy]\nstrict = false\n"), "environment"),
            ("failing Python test", lambda c: _sub(c / "pylib/lib.py", "a + b", "a - b"), "check"),
            ("Python lint finding", _append("pylib/lib.py", "\nimport os\n"), "check"),
            ("Python type error", _append("pylib/lib.py", "\n\ndef bad() -> int:\n    return 'x'\n"), "check"),
        ]  # fmt: skip
    return cases


BASELINE = {
    "rust-bazel-9.3": (True, False),
    "python-bazel-9.3": (False, True),
    "rust-python-bazel-9.3": (True, True),
}
for _p, (_r, _py) in BASELINE.items():
    NEGATIVE[_p] = _baseline_cases(_r, _py)
NEGATIVE["rust-cargo-1.99"] = NEGATIVE["rust-cargo"]
NEGATIVE["rust-bazel"] = _bazel_cases("8.4.1", "1.85.0", "1.84.0", "abseil-cpp", "20250127.1")
NEGATIVE["rust-bazel-9"] = _bazel_cases("9.1.0", "1.99.1", "1.99.0", "yaml-cpp", "0.8.0")


def commit_all(consumer: Path, genv: dict, msg: str) -> None:
    run(["git", "add", "-A"], consumer, genv)
    run(["git", "commit", "-qm", msg, "--allow-empty"], consumer, genv)


def negative_cases(profile: str, consumer: Path, genv: dict, env: dict, py: list) -> list[dict]:
    out = []
    for name, mutate, kind in NEGATIVE.get(profile, []):
        mutate(consumer)
        commit_all(consumer, genv, name)
        res = consumer.parent / f"{profile}.negative.json"
        run(
            [*py, "check", "--project", str(consumer), "--stage", "full", "--result", str(res)],
            ROOT,
            env,
            check=False,
        )
        doc = json.loads(res.read_text())
        bad_env = doc["environment"]["conformant"] is not True
        bad_check = any(c["state"] != "verified" for c in doc["checks"])
        ok = not doc["certification"]["certified"] and (bad_env if kind == "environment" else bad_check)
        out.append({"case": name, "rejected": ok, "blockers": doc["certification"]["blockers"]})
        run(["git", "reset", "-q", "--hard", "HEAD~1"], consumer, genv)
    return out


def prepare_baseline(consumer: Path, profile: str, env: dict, py: list) -> dict:
    """What a project does once per pinned release: materialize the platform's Bazel configuration, then
    resolve the module graph (the existing lockfile machinery, unchanged)."""
    manifest = json.loads((ROOT / "toolchains" / "manifest.json").read_text())
    run([*py, "toolchain", "materialize", "--manifest", str(ROOT / "toolchains" / "manifest.json"),
         "--project", str(consumer), "--profile", profile, "--add-hooks"], ROOT, env)  # fmt: skip
    sys.path.insert(0, str(ROOT / "src"))
    from dev_platform import toolchain

    benv = {**env, **toolchain.runtime_env(manifest, profile)}
    run(["bazel", "mod", "deps", "--lockfile_mode=update"], consumer, benv)
    return benv


DECOYS = ("rustc", "cargo", "rustup", "rustdoc", "clippy-driver", "python", "python3", "pip", "pip3",
          "pytest", "coverage", "ruff", "mypy")  # fmt: skip


def host_independence(consumer: Path, benv: dict, rust: bool, python: bool) -> dict:
    """Build, test and lint with decoy compilers, interpreters and tools first on PATH and as the action
    PATH: a host tool that was used is recorded and fails (exit 97), so it cannot go unnoticed."""
    import tempfile
    import uuid

    with tempfile.TemporaryDirectory(prefix="dp-decoy-") as td:
        decoy, log = Path(td) / "decoy", Path(td) / "decoy.log"
        decoy.mkdir()
        log.write_text("")
        for name in DECOYS:
            p = decoy / name
            p.write_text(f'#!/bin/sh\necho "$0 $*" >> "{log}"\nexit 97\n')
            p.chmod(0o755)
        bazel = shutil.which("bazel", path=benv.get("PATH"))
        assert bazel, "bazel is not on PATH"
        env = {**benv, "PATH": f"{decoy}:{Path(bazel).parent}:/usr/bin:/bin"}
        flags = ["--lockfile_mode=error", f"--action_env=PATH={decoy}:/usr/bin:/bin",
                 f"--action_env=DP_PROOF_NONCE={uuid.uuid4().hex}"]  # fmt: skip
        steps = {"test": ["bazel", "test", *flags, "--test_output=errors", "//..."],
                 "lint": ["bazel", "build", *flags, "--config=dp-lint", "//..."]}  # fmt: skip
        results = {k: run(v, consumer, env, check=False).returncode for k, v in steps.items()}
        invoked = [ln for ln in log.read_text().splitlines() if ln.strip()]
    return {"exit": results, "decoy_invocations": invoked[:5],
            "ok": not invoked and all(c == 0 for c in results.values())}  # fmt: skip


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--isolate-env", action="store_true", help="run the checks with a scrubbed environment")
    ap.add_argument("--negative", action="store_true", help="also run the must-be-rejected scenarios")
    ap.add_argument(
        "--app-release",
        action="store_true",
        help="also run the application-release chain over the certified result, with rejection cases",
    )
    a = ap.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    store = WORK / "store"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "DEV_PLATFORM_STORE": str(store)}
    version = make_store(env, store)
    consumer = WORK / "consumer"
    rmtree(consumer)
    shutil.copytree(ROOT / a.fixture, consumer, ignore=shutil.ignore_patterns("bazel-*", "target"))
    py = [sys.executable, "-m", "dev_platform"]
    run(
        [*py, "init", "--project", str(consumer), "--platform-version", version, "--profile", a.profile],
        ROOT,
        env,
    )
    genv = {**env, "GIT_AUTHOR_NAME": "q", "GIT_AUTHOR_EMAIL": "q@example.invalid",
            "GIT_COMMITTER_NAME": "q", "GIT_COMMITTER_EMAIL": "q@example.invalid"}  # fmt: skip
    benv = None
    if a.profile in BASELINE:
        benv = prepare_baseline(consumer, a.profile, env, py)
        run(
            [
                *py,
                "init",
                "--project",
                str(consumer),
                "--platform-version",
                version,
                "--profile",
                a.profile,
                "--force",
            ],
            ROOT,
            env,
        )  # fmt: skip  (again, now that the configuration exists: adds the lint and coverage checks)
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "fixture"]):
        run(["git", *cmd], consumer, genv)
    result = consumer.parent / f"{a.profile}.result.json"
    r = run(
        [*py, "check", "--project", str(consumer), "--stage", "full", "--result", str(result)]
        + (["--isolate-env"] if a.isolate_env else []),
        ROOT,
        env,
        check=False,
    )
    sys.stderr.write(r.stdout[-2000:])
    doc = json.loads(result.read_text())
    cert = doc["certification"]
    env_rec = doc["environment"]
    summary = {
        "profile": a.profile,
        "platform": f"{sys.platform}-{os.uname().machine}",
        "admission": doc["admission"],
        "checks": {c["id"]: c["state"] for c in doc["checks"]},
        "environment": {
            "assurance": env_rec["assurance"],
            "conformant": env_rec["conformant"],
            "tools": {t["name"]: t["identity"] for t in env_rec["tools"]},
            "identity_digest": env_rec["identity_digest"],
        },
        "execution": doc.get("execution"),
        "certified": cert["certified"],
        "blockers": cert["blockers"],
    }
    ok = cert["certified"]
    rust_profile = (
        "rust-toolchain"
        in json.loads((ROOT / "toolchains" / "manifest.json").read_text())["profiles"][a.profile]["tools"]
    )
    if rust_profile and ok:
        # Bazel must have compiled with its declared Rust toolchain, not a host rustc (issue #111).
        proof_file = WORK / f"{a.profile}.bazel-rust-proof.json"
        run([*py, "toolchain", "prove-bazel-rust", "--project", str(consumer), "--out", str(proof_file)],
            ROOT, env, check=False)  # fmt: skip
        proof = json.loads(proof_file.read_text()) if proof_file.is_file() else {"ok": False}
        summary["bazel_rust_toolchain"] = proof
        ok = bool(proof.get("ok"))
    if benv is not None and ok:
        summary["host_independence"] = host_independence(consumer, benv, *BASELINE[a.profile])
        ok = summary["host_independence"]["ok"]
    if a.negative and ok:
        summary["negative"] = negative_cases(a.profile, consumer, genv, env, py)
        ok = all(n["rejected"] for n in summary["negative"])
    if a.app_release and ok:
        sys.path.insert(0, str(ROOT / "tools"))
        import qualify_app_release

        summary["app_release"] = qualify_app_release.run(consumer, result, env, WORK / "app-release")
        ok = summary["app_release"].get("all_ok", False) or "skipped" in summary["app_release"]
    if a.out:
        a.out.write_text(json.dumps({"summary": summary, "result": doc}, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
