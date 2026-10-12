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

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipapp
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from recorded_repo import Repo  # noqa: E402

LOCKS = ("Cargo.lock", "MODULE.bazel.lock", "uv.lock", "requirements.txt", "poetry.lock")
APPROVER, STRANGER = "qualify-approver", "qualify-stranger"
REPO = "example/qualified-app"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecordedGitHub(Repo):
    """A recorded evidence repository (tools/recorded_repo.py) whose signed commits are the approver's by default."""

    def __init__(self) -> None:
        super().__init__()
        self.commit({"README.md": b"evidence repository\n"}, author="qualify-bot", committer="qualify-bot")

    def sign(self, path, raw, *, verified=True, author=APPROVER, committer=APPROVER, **kw) -> None:
        super().sign(path, raw, verified=verified, author=author, committer=committer, **kw)


def _artifact(consumer: Path, work: Path, git) -> tuple[Path, str, str, list[dict]]:
    """The artifact under approval. A hash-locked Python consumer is packaged as a real zipapp with its pinned
    dependencies installed by `pip --require-hashes`; any other consumer gets a `git archive` stand-in."""
    req = consumer / "requirements.txt"
    if not (req.is_file() and "--hash=sha256:" in req.read_text()):
        art = work / "source.tar"
        art.write_bytes(git("archive", "--format=tar", "HEAD"))
        return art, "source.tar", "git archive of the consumer HEAD (stand-in)", []
    extra: list[dict] = []
    tree = work / "zipapp-tree"
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir(parents=True)
    pip = [sys.executable, "-m", "pip", "install", "--no-deps", "--no-compile", "--only-binary=:all:",
           "--require-hashes", "--disable-pip-version-check", "--target", str(tree), "-r"]  # fmt: skip
    ok = subprocess.run([*pip, str(req)], capture_output=True, text=True)
    if ok.returncode:
        raise RuntimeError(f"pinned dependencies did not install: {ok.stderr[-300:]}")
    # the lock must actually bind: a wrong hash is refused by the installer itself
    bad = work / "requirements-bad-hash.txt"
    bad.write_text(re.sub(r"sha256:[0-9a-f]{8}", "sha256:00000000", req.read_text()))
    refused = subprocess.run([*pip, str(bad)], capture_output=True, text=True).returncode != 0
    extra.append({"case": "dependency with a wrong lock hash is refused at install", "expected": "refused",
                  "actual": "refused" if refused else "installed", "ok": refused})  # fmt: skip
    shutil.copy(consumer / "app.py", tree / "app.py")
    for f in tree.rglob("*"):
        os.utime(f, (315532800, 315532800))  # deterministic member times
    art = work / "app.pyz"
    zipapp.create_archive(tree, art, main="app:main", compressed=False)
    smoke = subprocess.run([sys.executable, str(art)], capture_output=True, text=True)
    extra.append({"case": "built zipapp runs with the locked dependency", "expected": "locked-app 3",
                  "actual": smoke.stdout.strip(), "ok": smoke.stdout.strip() == "locked-app 3"})  # fmt: skip
    return art, "app.pyz", "zipapp of the application with hash-locked dependencies installed by pip", extra


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
    art, art_name, art_note, extra = _artifact(consumer, work, git)

    def assemble_file(version: str, out: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "dev_platform", "provenance", "assemble", "--result", str(result_path),
             "--name", "qualified-app", "--app-version", version, "--source-uri", "https://example.invalid/app",
             "--artifact", f"{art_name}={hashlib.sha256(art.read_bytes()).hexdigest()}",
             *[x for lock in locks for x in ("--lock", str(lock))], "--root", str(consumer), "--out", str(out)],
            cwd=ROOT, env=env, capture_output=True, text=True)  # fmt: skip

    rel_path = work / "release.json"
    asm = assemble_file("1.0.0", rel_path)
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
               results=None, advisories=(), purpose="operational", audit_dir=None):  # fmt: skip
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
            artifacts={art_name: artifact}, results=[result_path] if results is None else results,
            advisories=list(advisories), authorizations=paths, gh=gh or default_gh, now=NOW,
            purpose=purpose, audit_dir=audit_dir)  # fmt: skip
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

    # authorization freshness: the current state is read from the evidence repository, not from what was supplied
    def revoked_elsewhere(name, **kw):
        """Only the approval is supplied; its revocation was published to the evidence repository on its own."""
        gh = RecordedGitHub()
        rv = work / f"{name}-rev.json"
        doc = approval(f"r-{name}", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        rv.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
        verify(
            [{"doc": approval(f"a-{name}")}], gh=gh, **{**kw, "purpose": "historical"}
        )  # commits the approval
        gh.sign(f"authorizations/r-{name}.json", rv.read_bytes())
        return gh

    def current_decision():
        gh = revoked_elsewhere("cur")
        return verify([{"doc": approval("a-cur")}], gh=gh)

    def historical_inspection():
        gh = revoked_elsewhere("hist")
        return verify([{"doc": approval("a-hist")}], gh=gh, purpose="historical")

    case(
        "approval, then a revocation published independently and absent from the supplied records",
        "unapproved",
        current_decision,
    )
    case(
        "the same evidence inspected as history shows only a historical approval, never approved",
        "historical-approval",
        historical_inspection,
    )

    def outage():
        gh = RecordedGitHub()
        gh.fail = lambda ep: True
        return verify(good(), gh=gh)

    case("evidence repository unreachable (current state unverifiable)", "indeterminate", outage)

    def deleted_revocation():
        gh = RecordedGitHub()
        verify(
            [
                {"doc": approval("a7")},
                {"doc": approval("r7", decision="revoked", decided_at="2026-10-11T10:00:00Z")},
            ],
            gh=gh,
        )
        gh.delete("authorizations/r7.json", author="intruder", committer="intruder")
        return verify([], gh=gh)

    case("revocation deleted from the evidence history", "indeterminate", deleted_revocation)

    def deleted_and_acknowledged():
        gh = RecordedGitHub()
        verify(
            [
                {"doc": approval("a8")},
                {"doc": approval("r8", decision="revoked", decided_at="2026-10-11T10:00:00Z")},
            ],
            gh=gh,
        )
        gone = gh.delete("authorizations/r8.json", author="intruder", committer="intruder")
        ack = {**policy, "authorization": {**policy["authorization"],
               "acknowledged_removals": [{"path": "authorizations/r8.json", "commit": gone}]}}  # fmt: skip
        return verify([], gh=gh, pol=ack)

    case(
        "deleted revocation acknowledged in the pinned policy still revokes",
        "unapproved",
        deleted_and_acknowledged,
    )

    def audited_then_rewritten():
        gh = RecordedGitHub()
        ad = work / "audit-rewrite"
        verify([{"doc": approval("a9")}, {"doc": approval("r9", decision="revoked", decided_at="2026-10-11T10:00:00Z")}],
               gh=gh, audit_dir=ad)  # fmt: skip
        gh.rewind(1)  # force-push: the revocation commit disappears from the branch
        gh.commit({"notes.txt": b"x"}, author="bot", committer="bot")
        return verify([], gh=gh, audit_dir=ad)

    case("history rewritten after it was audited", "indeterminate", audited_then_rewritten)

    def warm_equals_cold():
        gh = RecordedGitHub()
        ad = work / "audit-warm"
        verify([{"doc": approval("a10")}, {"doc": approval("r10", decision="revoked", decided_at="2026-10-11T10:00:00Z")}],
               gh=gh, audit_dir=ad)  # fmt: skip
        warm, cold = verify([], gh=gh, audit_dir=ad), verify([], gh=gh)
        return warm if warm == cold else f"warm {warm} != cold {cold}"

    case("a warm audit state decides exactly as a cold run", "unapproved", warm_equals_cold)
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

    def assemble(version: str) -> dict:
        out = work / f"release-{version}.json"
        r = assemble_file(version, out)
        if r.returncode:
            raise RuntimeError(f"assemble {version}: {(r.stderr or r.stdout)[-300:]}")
        return json.loads(out.read_text())

    qualify_rollback = _load("qualify_rollback", ROOT / "tools" / "qualify_rollback.py")
    default_gh = RecordedGitHub()
    rollback = qualify_rollback.run(
        env=env, work=work, result_path=result_path, assemble=assemble, approval=approval,
        double=default_gh, policy=policy, app="qualified-app")  # fmt: skip
    return {
        "assembled": True,
        "rollback": rollback,
        "release_sha256": _digest(rel),
        "artifact": art_note,
        "double": "GitHub is a recording double at the gh api boundary; all verification code is real",
        "cases": cases + extra,
        "all_ok": all(c["ok"] for c in cases + extra) and rollback["all_ok"],
    }
