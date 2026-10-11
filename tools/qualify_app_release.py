#!/usr/bin/env python3
"""Application-release chain over a REAL certified result, with must-be-rejected cases (v0.3.0).

Used by tools/qualify.py --app-release after the real build-system run certified. Everything except GitHub is
real: the result record comes from the real run, `dev-platform provenance assemble` builds the release record, and
the independent verifier (tools/verify_app_release.py, with the provider registry of tools/verify_release.py)
judges it. GitHub is replaced at the `gh api` boundary by a recording double that serves the signed-commit
evidence the registry asks for; it is a test double, not a claim about GitHub.

The "artifact" is `git archive HEAD` of the consumer: a deterministic stand-in for a built artifact, because
qualification fixtures do not publish one. The chain, not the artifact kind, is what is exercised.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKS = ("Cargo.lock", "MODULE.bazel.lock", "uv.lock", "requirements.txt", "poetry.lock")
APPROVER, STRANGER = "qualify-approver", "qualify-stranger"
REPO = "example/qualified-app"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecordedGitHub:
    """`gh api` double: commit history with verification fields, and file contents by commit."""

    def __init__(self) -> None:
        self.history: dict[str, list[dict]] = {}

    def sign(self, path: str, raw: bytes, *, verified=True, author=APPROVER, committer=APPROVER) -> None:
        c = {
            "sha": f"{len(self.history.get(path, [])) + 1:040x}",
            "commit": {"verification": {"verified": verified, "reason": "valid" if verified else "unsigned"}},
            "author": {"login": author},
            "committer": {"login": committer},
            "_content": raw,
        }
        self.history.setdefault(path, []).insert(0, c)

    def __call__(self, argv):
        ep = argv[2]
        m = re.search(r"/commits\?sha=([^&]+)&path=([^&]+)", ep)
        if m:
            hist = [{k: v for k, v in c.items() if k != "_content"} for c in self.history.get(m.group(2), [])]
            return 0, json.dumps(hist), ""
        m = re.search(r"/contents/([^?]+)\?ref=(\w+)", ep)
        if m:
            for c in self.history.get(m.group(1), []):
                if c["sha"] == m.group(2):
                    return 0, json.dumps({"content": base64.b64encode(c["_content"]).decode()}), ""
        return 1, "", "not found"


def _digest(doc) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(consumer: Path, result_path: Path, env: dict, work: Path) -> dict:
    """The chain and its rejections for a consumer whose full-stage run just certified."""
    A = _load("verify_app_release_q", ROOT / "tools" / "verify_app_release.py")
    pv_path = ROOT / "tools" / "verify_release.py"
    V = A.load_platform_verifier(pv_path, hashlib.sha256(pv_path.read_bytes()).hexdigest())
    work.mkdir(parents=True, exist_ok=True)
    result = json.loads(result_path.read_text())
    git = lambda *a: subprocess.run(["git", *a], cwd=consumer, check=True, capture_output=True).stdout  # noqa: E731
    rev = git("rev-parse", "HEAD").decode().strip()
    locks = [consumer / n for n in LOCKS if (consumer / n).is_file()]
    if not locks:
        return {"skipped": "fixture has no lock file the chain knows"}
    art = work / "source.tar"
    art.write_bytes(git("archive", "--format=tar", "HEAD"))
    rel_path = work / "release.json"
    asm = subprocess.run(
        [sys.executable, "-m", "dev_platform", "provenance", "assemble", "--result", str(result_path),
         "--name", "qualified-app", "--app-version", "1.0.0", "--source-uri", "https://example.invalid/app",
         "--artifact", f"source.tar={hashlib.sha256(art.read_bytes()).hexdigest()}",
         *[x for lock in locks for x in ("--lock", str(lock))], "--root", str(consumer), "--out", str(rel_path)],
        cwd=ROOT, env=env, capture_output=True, text=True)  # fmt: skip
    if asm.returncode:
        return {"assembled": False, "detail": (asm.stderr or asm.stdout)[-400:]}
    rel = json.loads(rel_path.read_text())
    plat = rel["platform"]
    policy = {
        "schema": "dev-platform.app-trust/v1",
        "authorization": {
            "providers": ["github-signed-commit"], "evidence_repo": REPO, "evidence_ref": "main",
            "approvers": [{"id": "qa", "provider": "github-signed-commit", "login": APPROVER,
                           "roles": ["release-approver"], "may_approve": ["application-release"],
                           "may_confer": ["application-release-approval"], "applications": ["qualified-app"]}],
        },
        "platform_releases": [{"version": plat["release_version"], "tree_digest": plat["release_tree_digest"]}],
    }  # fmt: skip

    def approval(name, release=rel, **over):
        d = {
            "schema": "dev-platform.authorization/v1", "id": name,
            "subject": {"kind": "application-release", "digest": _digest(release)},
            "decision": "approved",
            "decided_by": {"id": "qa", "role": "release-approver", "identity_assertion": {
                "provider": "github-signed-commit", "login": APPROVER, "path": f"authorizations/{name}.json"}},
            "basis": {"kind": "qualification", "reference": "tools/qualify_app_release.py"},
            "decided_at": "2026-10-10T10:00:00Z",
            "scope": {"confers": ["application-release-approval"]},
            "retention": {"class": "standard", "until": None},
        }  # fmt: skip
        d.update(over)
        return d

    def verify(auths, *, release=rel, pol=policy, gh=None, rev_pin=rev, lock_files=locks, artifact=art,
               results=None, advisories=()):  # fmt: skip
        paths = []
        for i, a in enumerate(auths):
            p = work / f"auth-{i}.json"
            p.write_text(json.dumps(a["doc"], sort_keys=True, indent=2) + "\n")
            paths.append(p)
            (gh or default_gh).sign(
                f"authorizations/{a['doc']['id']}.json", p.read_bytes(), **a.get("sign", {})
            )
        rp = work / "rel-under-test.json"
        rp.write_text(json.dumps(release, sort_keys=True))
        out = A.verify(
            rp, pol, V, mode="release", source_revision=rev_pin, locks=lock_files, lock_root=consumer,
            artifacts={"source.tar": artifact}, results=[result_path] if results is None else results,
            advisories=list(advisories), authorizations=paths, gh=gh or default_gh, now=NOW)  # fmt: skip
        return out["approval"]["state"]

    cases, default_gh = [], None

    def case(name, want, fn):
        nonlocal default_gh
        default_gh = RecordedGitHub()
        got = fn()
        cases.append({"case": name, "expected": want, "actual": got, "ok": got == want})

    good = lambda: [{"doc": approval("a-good")}]  # noqa: E731
    case("authenticated approval of the exact release", "approved", lambda: verify(good()))
    case("no approval at all", "unapproved", lambda: verify([]))
    case(
        "unsigned approval",
        "unapproved",
        lambda: verify([{"doc": approval("a1"), "sign": {"verified": False}}]),
    )
    case("approval by an authenticated non-approver", "unapproved", lambda: verify(
        [{"doc": approval("a2"), "sign": {"author": STRANGER, "committer": STRANGER}}]))  # fmt: skip
    case("approval of a different release", "unapproved", lambda: verify(
        [{"doc": approval("a3", release={**rel, "application": {**rel["application"], "version": "9.9.9"}})}]))  # fmt: skip
    case("authentic revocation after approval", "unapproved", lambda: verify(
        [{"doc": approval("a4")}, {"doc": approval("r4", decision="revoked", decided_at="2026-10-11T10:00:00Z")}]))  # fmt: skip
    case("source revision pin differs", "failed", lambda: verify(good(), rev_pin="0" * 40))
    stale = copy.deepcopy(result)
    stale["revision"] = "f" * 40
    stale_p = work / "stale-result.json"
    stale_p.write_text(json.dumps(stale))
    case("manipulated result (digest no longer matches)", "failed", lambda: verify(good(), results=[stale_p]))
    case("evidence missing", "failed", lambda: verify(good(), results=[]))
    tampered_art = work / "tampered.tar"
    tampered_art.write_bytes(art.read_bytes() + b"x")
    case("artifact bytes differ", "failed", lambda: verify(good(), artifact=tampered_art))
    lock_copy = work / "lock-copy"
    lock_copy.mkdir(exist_ok=True)
    changed = []
    for lock in locks:
        (lock_copy / lock.name).write_bytes(lock.read_bytes() + b"\n#changed\n")
        changed.append(lock_copy / lock.name)
    orig_root = consumer

    def lock_changed():
        nonlocal consumer
        consumer = lock_copy
        try:
            return verify(good(), lock_files=changed)
        finally:
            consumer = orig_root

    case("dependency state differs", "failed", lock_changed)
    other_policy = copy.deepcopy(policy)
    other_policy["platform_releases"] = [{"version": plat["release_version"], "tree_digest": "5" * 64}]
    case(
        "platform release not allowed by the application policy",
        "failed",
        lambda: verify(good(), pol=other_policy),
    )
    adv = work / "advisory.json"
    adv.write_text(json.dumps({"schema": "dev-platform.advisory/v1", "id": "QUAL-1", "summary": "s",
                               "severity": "high", "affected": [{"component": "dev-platform",
                               "versions": [plat["release_version"]]}]}))  # fmt: skip
    case("security advisory on the platform release", "failed", lambda: verify(good(), advisories=[adv]))
    return {
        "assembled": True,
        "release_sha256": _digest(rel),
        "artifact": "git archive of the consumer HEAD (stand-in)",
        "double": "GitHub is a recording double at the gh api boundary; all verification code is real",
        "cases": cases,
        "all_ok": all(c["ok"] for c in cases),
    }
