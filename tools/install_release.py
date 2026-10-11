#!/usr/bin/env python3
"""Trusted installation of a dev-platform release.

Nothing from the archive is imported or executed here. The order is fixed:

  1. self-check: this script's sibling `verify_release.py` and the trust policy must have exactly the
     sha256 the operator pinned (--verifier-sha256, --policy-sha256). The pins come from outside the
     artifact being installed; without them nothing proceeds.
  2. obtain the archive (a local file, or `gh release download` into a private directory).
  3. independent verification (verify_release.verify): archive digest, structure, version binding,
     source revision, SBOM correspondence, provenance and SBOM attestations against the signer policy.
  4. admission by acceptance state: `accepted`, or an explicitly allowed weaker state. A pre-release
     needs --allow-prerelease; a verified-but-unaccepted stable release needs --allow-unaccepted.
  5. only then: extract the *verified bytes* into staging, require the tree digest to equal the one
     verification computed (and the consumer's pin when given), freeze read-only and rename into the
     write-once store. The verification record is stored beside it.

Exit status: 0 installed (or already installed identically), 1 refused, 2 usage/config, 3 trust-base
self-check failed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATES_ORDER = ("accepted", "verified-unaccepted", "pre-release")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Refused(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def load_verifier(path: Path, pinned: str):
    """Import the verifier only after its bytes are checked against the operator's pin."""
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != pinned:
        raise Refused(f"verifier {path} does not match the pinned sha256", 3)
    mod = types.ModuleType("verify_release")
    exec(compile(data, str(path), "exec"), mod.__dict__)
    return mod


def load_policy(path: Path, pinned: str) -> dict:
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != pinned:
        raise Refused(f"trust policy {path} does not match the pinned sha256", 3)
    return json.loads(data)


def resolve_revision(repo_url: str, version: str) -> str:
    """The expected commit, from git's view of the tag (independent of the release assets)."""
    ref = f"refs/tags/v{version}"
    r = subprocess.run(
        ["git", "ls-remote", repo_url, ref, ref + "^{}"], capture_output=True, text=True, timeout=120
    )
    lines = [ln.split() for ln in r.stdout.splitlines() if ln.strip()]
    peeled = [sha for sha, name in lines if name.endswith("^{}")]
    plain = [sha for sha, name in lines if not name.endswith("^{}")]
    sha = (peeled or plain or [None])[0]
    if r.returncode != 0 or not sha:
        raise Refused(f"cannot resolve {ref} from {repo_url}")
    return sha


def download(repo: str, version: str, dest: Path) -> Path:
    name = f"dev-platform-{version}.tar.gz"
    r = subprocess.run(
        [
            "gh",
            "release",
            "download",
            f"v{version}",
            "--repo",
            repo,
            "--pattern",
            name,
            "--pattern",
            f"dev-platform-{version}.build-environment.json",
            "--pattern",
            f"dev-platform-{version}.continuity.json",
            "--dir",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if r.returncode != 0 or not (dest / name).is_file():
        raise Refused(f"download failed: {r.stderr.strip()[:200]}")
    return dest / name


def extract_verified(archive: Path, dest: Path, root_name: str) -> Path:
    """Extract regular files and directories only, under exactly one root named like the version."""
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar:
            parts = Path(m.name).parts
            if not (m.isfile() or m.isdir()) or m.name.startswith("/") or ".." in parts or not parts:
                raise Refused(f"unsafe archive member {m.name!r}")
            if parts[0] != root_name:
                raise Refused(f"member {m.name!r} outside root {root_name!r}")
            target = dest / m.name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                if src is None:
                    raise Refused(f"unreadable member {m.name!r}")
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(src.read())
    return dest / root_name


def freeze(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root):
        for n in filenames:
            p = Path(dirpath) / n
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    for dirpath, dirnames, _ in os.walk(root, topdown=False):
        for n in dirnames:
            p = Path(dirpath) / n
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    root.chmod(root.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def admit(state: str, *, allow_prerelease: bool, allow_unaccepted: bool) -> None:
    if state == "accepted":
        return
    if state == "pre-release" and allow_prerelease:
        return
    if state == "verified-unaccepted" and allow_unaccepted:
        return
    raise Refused(f"acceptance state {state!r} is not admitted (see --allow-prerelease/--allow-unaccepted)")


def install(
    archive: Path,
    store: Path,
    exp: dict,
    verifier,
    policy: dict,
    *,
    gh=None,
    authorizations=(),
    bundle=None,
    sbom_bundle=None,
    allow_prerelease=False,
    allow_unaccepted=False,
    environment=None,
    continuity_record=None,
    expect_tree: str | None = None,
    previous_record: dict | None = None,
) -> tuple[Path, dict]:
    kw = {"gh": gh} if gh else {}
    if continuity_record is not None:  # older pinned verifiers have no such parameter and no such policy key
        kw["continuity"] = continuity_record
    record = verifier.verify(
        archive,
        exp,
        policy,
        authorizations=list(authorizations),
        bundle=bundle,
        sbom_bundle=sbom_bundle,
        environment=environment,
        **kw,
    )
    state = record["acceptance"]["state"]
    if state == "failed":
        bad = [c["id"] for c in record["checks"] if c["status"] == "failed"]
        raise Refused(f"verification failed: {', '.join(bad)}")
    admit(state, allow_prerelease=allow_prerelease, allow_unaccepted=allow_unaccepted)
    tree = record["subject"]["tree_digest"]
    if expect_tree and tree != expect_tree:
        raise Refused(f"tree digest {tree} != the consumer's pin {expect_tree}")
    record["continuity"] = continuity(record, previous_record)
    record["installation"] = {"admitted_state": state, "tree_digest": tree}
    version = exp["version"]
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    dest = store / version
    if dest.exists():
        if verifier.tree_digest(dest) == tree:
            return dest, record  # idempotent: identical bytes already installed
        raise Refused(f"{dest} exists with different content; releases are write-once")
    stage = Path(tempfile.mkdtemp(prefix=f".install-{version}-", dir=store))
    try:
        rel = extract_verified(archive, stage, version)
        if verifier.tree_digest(rel) != tree:
            raise Refused("extracted tree differs from the verified tree")
        os.rename(rel, dest)
        freeze(dest)
        rec_dir = store / ".records"
        rec_dir.mkdir(exist_ok=True)
        (rec_dir / f"{version}.verification.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n"
        )
    finally:
        for dirpath, dirnames, filenames in os.walk(stage):
            for n in dirnames + filenames:
                with contextlib.suppress(OSError):
                    (Path(dirpath) / n).chmod(0o700)
        shutil.rmtree(stage, ignore_errors=True)
    return dest, record


def continuity(record: dict, previous: dict | None) -> dict:
    """Evidence that this release continues a previously verified one. Informational only: a previous
    release is never the root of trust, the operator's pins are."""
    if not previous:
        return {"previous": None}
    same = previous.get("policy_sha256") == record.get("policy_sha256")
    return {
        "previous": previous.get("subject", {}).get("version"),
        "previous_acceptance": previous.get("acceptance", {}).get("state"),
        "policy_unchanged": same,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--verifier-sha256", required=True, help="pinned sha256 of tools/verify_release.py")
    ap.add_argument("--policy", type=Path, default=HERE.parent / "trust" / "policy.json")
    ap.add_argument("--policy-sha256", required=True, help="pinned sha256 of the trust policy file")
    ap.add_argument("--archive", type=Path, help="local archive (default: download the GitHub release)")
    ap.add_argument("--repo", default="syncom-systems/dev-platform")
    ap.add_argument("--source-revision", help="expected commit; default: resolved from the git tag")
    ap.add_argument("--archive-sha256", help="expected archive sha256 (recommended: from your pin record)")
    ap.add_argument("--tree-sha256", help="expected tree digest (your consumer pin)")
    ap.add_argument("--authorization", type=Path, action="append", default=[])
    ap.add_argument(
        "--previous-record", type=Path, help="verification record of a previously installed release"
    )
    ap.add_argument(
        "--environment", type=Path, help="build-environment record (default: next to the archive)"
    )
    ap.add_argument(
        "--continuity", type=Path, help="predecessor-continuity record (default: next to the archive)"
    )
    ap.add_argument("--allow-prerelease", action="store_true")
    ap.add_argument("--allow-unaccepted", action="store_true")
    a = ap.parse_args(argv)
    try:
        verifier = load_verifier(HERE / "verify_release.py", a.verifier_sha256)
        policy = load_policy(a.policy, a.policy_sha256)
        if policy.get("schema") != verifier.POLICY_SCHEMA:
            raise Refused("policy schema not understood", 2)
        with tempfile.TemporaryDirectory(prefix="dp-install-") as tmp:
            archive = a.archive or download(a.repo, a.version, Path(tmp))
            env_file = a.environment or archive.parent / f"dev-platform-{a.version}.build-environment.json"
            cont_file = a.continuity or archive.parent / f"dev-platform-{a.version}.continuity.json"
            rev = a.source_revision or resolve_revision(f"https://github.com/{a.repo}", a.version)
            exp = {
                "version": a.version,
                "source_revision": rev,
                "archive_sha256": a.archive_sha256 or sha256_file(archive),
                "ref": f"refs/tags/v{a.version}",
            }
            if a.tree_sha256:
                exp["tree_digest"] = a.tree_sha256
            prev = json.loads(a.previous_record.read_text()) if a.previous_record else None
            dest, record = install(
                archive,
                a.store,
                exp,
                verifier,
                policy,
                authorizations=a.authorization,
                allow_prerelease=a.allow_prerelease,
                allow_unaccepted=a.allow_unaccepted,
                environment=env_file if env_file.is_file() else None,
                continuity_record=cont_file if cont_file.is_file() else None,
                expect_tree=a.tree_sha256,
                previous_record=prev,
            )
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return e.code
    print(
        f"installed {dest}\nacceptance: {record['acceptance']['state']}\npin sha256 = {record['subject']['tree_digest']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
