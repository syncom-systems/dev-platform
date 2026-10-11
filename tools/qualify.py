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


def _lock_tamper(c: Path) -> None:
    lock = json.loads((c / "MODULE.bazel.lock").read_text())
    for k in lock["registryFileHashes"]:
        if "/rules_rust/" in k and k.endswith("source.json"):
            lock["registryFileHashes"][k] = "0" * 64
    (c / "MODULE.bazel.lock").write_text(json.dumps(lock, indent=2))


# profile -> [(name, mutation, what must be true afterwards)]. Each must end NOT certified.
NEGATIVE = {
    "rust-bazel": [
        ("resolved graph tampered", _lock_tamper, "environment"),
        ("undeclared module change (lockfile_mode=error)", lambda c: _sub(c / "MODULE.bazel", 'module(name = "rust_demo", version = "0.1.0")', 'module(name = "rust_demo", version = "0.1.0")\nbazel_dep(name = "abseil-cpp", version = "20250127.1")'), "check"),
        ("declared bazel version differs", lambda c: (c / ".bazelversion").write_text("8.4.1\n"), "environment"),
        ("declared rust version differs", lambda c: _sub(c / "MODULE.bazel", "1.85.0", "1.84.0"), "environment"),
        ("failing test", lambda c: _sub(c / "src/lib.rs", "assert_eq!(super::add(2, 3), 5)", "assert_eq!(super::add(2, 3), 6)"), "check"),
    ],
    "rust-cargo": [
        ("failing test", lambda c: _sub(c / "src/lib.rs", "assert_eq!(super::add(2, 3), 5)", "assert_eq!(super::add(2, 3), 6)"), "check"),
        ("lock file out of date (--locked)", lambda c: _sub(c / "Cargo.toml", 'edition = "2021"', 'edition = "2021"\n\n[dependencies]\nsmallvec = "1"'), "check"),
    ],
    "rust-cargo-1.99": None,  # same cases as rust-cargo, set below
    "python": [
        ("failing test", lambda c: _sub(c / "app.py", "a + b", "a - b"), "check"),
    ],
}  # fmt: skip

NEGATIVE["rust-cargo-1.99"] = NEGATIVE["rust-cargo"]


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--isolate-env", action="store_true", help="run the checks with a scrubbed environment")
    ap.add_argument("--negative", action="store_true", help="also run the must-be-rejected scenarios")
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
    if a.negative and ok:
        summary["negative"] = negative_cases(a.profile, consumer, genv, env, py)
        ok = all(n["rejected"] for n in summary["negative"])
    if a.out:
        a.out.write_text(json.dumps({"summary": summary, "result": doc}, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
