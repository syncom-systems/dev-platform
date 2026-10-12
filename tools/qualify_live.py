#!/usr/bin/env python3
"""Application-release approval against LIVE GitHub (signature and commit-history path), with a test identity.

Everything is the shipped code with the real `gh` binary and real api.github.com answers: no double. The evidence
repository is a controlled private fixture (default syncom-systems/dev-platform-qualification-fixture) that holds no
application. Its only identity is `github-actions[bot]`, driven by the fixture's `record` workflow; nobody's
personal account signs anything, and no real application is named.

What this can and cannot show, by construction:
  * GitHub signs a record committed through its API with its own key and names `web-flow` as committer. The
    verifier requires author == committer == the approver, so such a record is REFUSED (live proof of that rule).
  * A genuine acceptance needs a second GitHub identity with its own registered signing key (author == committer,
    signature valid). No such test identity exists yet, so the live path never reaches `approved`; that final
    positive is only exercised against the recording double (tools/qualify_rollback.py) and stays a stated limit.

Usage: python tools/qualify_live.py --qualification qualification.json --out live.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
BOT = "github-actions[bot]"
APP = "live-fixture-app"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r.stdout


def dispatch_record(repo: str, path: str, raw: bytes) -> str:
    """Run the fixture's `record` workflow (as github-actions[bot]); returns the commit sha it created."""
    before = json.loads(
        gh("run", "list", "-R", repo, "--workflow", "record.yml", "--json", "databaseId", "-L", "1") or "[]"
    )
    gh(
        "workflow",
        "run",
        "record.yml",
        "-R",
        repo,
        "-f",
        f"path={path}",
        "-f",
        f"content_b64={base64.b64encode(raw).decode()}",
    )
    for _ in range(60):
        time.sleep(3)
        runs = json.loads(
            gh(
                "run",
                "list",
                "-R",
                repo,
                "--workflow",
                "record.yml",
                "--json",
                "databaseId,status,conclusion",
                "-L",
                "1",
            )
        )
        fresh = runs and (not before or runs[0]["databaseId"] != before[0]["databaseId"])
        if fresh and runs[0]["status"] == "completed":
            if runs[0]["conclusion"] != "success":
                raise RuntimeError(f"record workflow {runs[0]['conclusion']}")
            break
    else:
        raise RuntimeError("record workflow did not finish")
    commits = json.loads(gh("api", f"repos/{repo}/commits?sha=main&path={path}&per_page=1"))
    return commits[0]["sha"]


def unsigned_commit(repo: str, path: str, raw: bytes) -> str:
    """Commit `path` with NO signature through the git data API (author/committer are an unlinked address)."""
    head = json.loads(gh("api", f"repos/{repo}/git/ref/heads/main"))["object"]["sha"]
    base = json.loads(gh("api", f"repos/{repo}/git/commits/{head}"))["tree"]["sha"]
    blob = json.loads(
        gh(
            "api",
            "-X",
            "POST",
            f"repos/{repo}/git/blobs",
            "-f",
            f"content={base64.b64encode(raw).decode()}",
            "-f",
            "encoding=base64",
        )
    )["sha"]
    body = json.dumps(
        {"base_tree": base, "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob}]}
    )
    tree = json.loads(
        subprocess.run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/git/trees", "--input", "-"],
            input=body,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )["sha"]
    who = {
        "name": "qualification",
        "email": "qualification@example.invalid",
        "date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    body = json.dumps(
        {
            "message": f"unsigned record {path}",
            "tree": tree,
            "parents": [head],
            "author": who,
            "committer": who,
        }
    )
    c = json.loads(
        subprocess.run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/git/commits", "--input", "-"],
            input=body,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )["sha"]
    gh("api", "-X", "PATCH", f"repos/{repo}/git/refs/heads/main", "-f", f"sha={c}")
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--qualification", type=Path, required=True, help="tools/qualify.py --out file (certified result)"
    )
    ap.add_argument("--repo", default="syncom-systems/dev-platform-qualification-fixture")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)

    from dev_platform import provenance, records

    A = load("verify_app_release", ROOT / "tools/verify_app_release.py")
    pv = ROOT / "tools/verify_release.py"
    V = A.load_platform_verifier(pv, hashlib.sha256(pv.read_bytes()).hexdigest())
    result = json.loads(a.qualification.read_text())["result"]
    rel = provenance.assemble(result, name=APP, version="0.0.1", source_uri="https://example.invalid/fixture",
                              artifacts=[{"name": "x", "sha256": "0" * 64}], resolution="0" * 64)  # fmt: skip
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    plat = rel["platform"]

    def policy(repo=a.repo, login=BOT):
        return {
            "schema": "dev-platform.app-trust/v1",
            "authorization": {"providers": ["github-signed-commit"], "evidence_repo": repo, "evidence_ref": "main",
                              "approvers": [{"id": "fixture-bot", "provider": "github-signed-commit", "login": login,
                                             "roles": ["release-approver"], "may_approve": ["application-release"],
                                             "may_confer": ["application-release-approval"], "applications": [APP]}]},
            "platform_releases": [{"version": plat["release_version"], "tree_digest": plat["release_tree_digest"]}],
        }  # fmt: skip

    def record(name, login=BOT):
        return {
            "schema": "dev-platform.authorization/v1", "id": name,
            "subject": {"kind": "application-release", "digest": records.canonical_digest(rel)},
            "decision": "approved",
            "decided_by": {"id": "fixture-bot", "role": "release-approver", "identity_assertion": {
                "provider": "github-signed-commit", "login": login, "path": f"authorizations/{name}.json"}},
            "basis": {"kind": "qualification", "reference": "tools/qualify_live.py"},
            "decided_at": "2026-10-10T10:00:00Z", "scope": {"confers": ["application-release-approval"]},
            "retention": {"class": "standard", "until": None},
        }  # fmt: skip

    tmp = Path(tempfile.mkdtemp(prefix="qualify-live-"))
    rel_path = tmp / "release.json"
    rel_path.write_text(json.dumps(rel, sort_keys=True))
    res_path = tmp / "result.json"
    res_path.write_text(json.dumps(result, sort_keys=True))
    cases: list[dict] = []

    def judge(name, auths, pol, want_state, needle, **kw):
        out = A.verify(rel_path, pol, V, mode="select", results=[res_path], authorizations=auths, **kw)
        probs = " | ".join(p for v in out["approval"]["authorization_evidence"] for p in v["problems"])
        got = out["approval"]["state"]
        failed = [c["id"] for c in out["checks"] if c["status"] == "failed"]
        ok = got == want_state and needle in (
            probs + " ".join(failed + [c["detail"] for c in out["checks"] if c["status"] == "failed"])
        )
        cases.append(
            {"case": name, "ok": ok, "expected": want_state, "actual": got, "reason": probs or failed}
        )
        return out

    def local(name, doc=None, raw=None):
        p = tmp / f"{name}.json"
        p.write_bytes(raw if raw is not None else (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())
        return p

    # 1. record that was never committed
    n = f"live-{stamp}-uncommitted"
    judge(
        "record never committed to the evidence repository",
        [local(n, record(n))],
        policy(),
        "unapproved",
        "no commit on main touches",
    )
    # 2. validly signed by GitHub, authored by the bot, committed by web-flow
    n = f"live-{stamp}-bot"
    raw = (json.dumps(record(n), indent=2, sort_keys=True) + "\n").encode()
    sha = dispatch_record(a.repo, f"authorizations/{n}.json", raw)
    c = json.loads(gh("api", f"repos/{a.repo}/commits/{sha}"))
    fields = {"verified": c["commit"]["verification"]["verified"], "reason": c["commit"]["verification"]["reason"],
              "author": (c["author"] or {}).get("login"), "committer": (c["committer"] or {}).get("login")}  # fmt: skip
    cases.append({"case": "live API reports a valid GitHub signature with author github-actions[bot] and committer web-flow",
                  "ok": fields == {"verified": True, "reason": "valid", "author": BOT, "committer": "web-flow"}, "observed": fields})  # fmt: skip
    bot_file = local(n, raw=raw)
    judge(
        "valid GitHub signature but committer web-flow is refused (committer is not the approver)",
        [bot_file],
        policy(),
        "unapproved",
        "committer of commit",
    )
    # 3. unsigned commit
    n2 = f"live-{stamp}-unsigned"
    raw2 = (json.dumps(record(n2), indent=2, sort_keys=True) + "\n").encode()
    unsigned_sha = unsigned_commit(a.repo, f"authorizations/{n2}.json", raw2)
    judge(
        "unsigned commit of a record",
        [local(n2, raw=raw2)],
        policy(),
        "unapproved",
        "not a validly signed commit",
    )
    # 4. evidence repository that does not exist / is not readable
    judge(
        "unreadable evidence repository fails closed",
        [bot_file],
        policy(repo="syncom-systems/does-not-exist-qualification"),
        "failed",
        "authorization-currency",
    )
    # 5. discovery against the live repository: every record in it is judged, none can approve
    out = judge(
        "discovering every record in the live evidence repository still approves nothing",
        [],
        policy(),
        "unapproved",
        "committer of commit",
    )
    cur = out["currency"]
    live_head = json.loads(gh("api", f"repos/{a.repo}/commits/main"))["sha"]
    cases.append({"case": "the current state was read live at one commit of the evidence ref", "ok": cur["status"] == "current" and cur["evidence"]["head_commit"] == live_head and cur["evidence"]["removed"] == [] and cur["evidence"]["history_commits"] >= 2 and cur["valid_until"] is not None, "currency": cur})  # fmt: skip
    judge(
        "historical inspection of the same record over the live repository is not an approval either",
        [bot_file],
        policy(),
        "unapproved",
        "committer of commit",
        purpose="historical",
    )
    # 5b. a record deleted from the evidence history (on a scratch branch of the fixture) makes the state unverifiable
    branch = f"qual-deleted-{stamp}"
    main_sha = json.loads(gh("api", f"repos/{a.repo}/git/ref/heads/main"))["object"]["sha"]
    gh(
        "api",
        "-X",
        "POST",
        f"repos/{a.repo}/git/refs",
        "-f",
        f"ref=refs/heads/{branch}",
        "-f",
        f"sha={main_sha}",
    )
    dpath = f"authorizations/live-{stamp}-deleted.json"
    put = json.loads(gh("api", "-X", "PUT", f"repos/{a.repo}/contents/{dpath}", "-f", "message=record to be deleted",
                        "-f", f"content={base64.b64encode(b'{}').decode()}", "-f", f"branch={branch}"))  # fmt: skip
    gh("api", "-X", "DELETE", f"repos/{a.repo}/contents/{dpath}", "-f", "message=delete the record",
       "-f", f"sha={put['content']['sha']}", "-f", f"branch={branch}")  # fmt: skip
    deleted_pol = policy()
    deleted_pol["authorization"]["evidence_ref"] = branch
    judge(
        "a record deleted from the live evidence history makes the current state unverifiable",
        [],
        deleted_pol,
        "failed",
        "authorization-currency",
    )
    cases.append({"case": "discovery listed live records", "ok": len(out["approval"]["authorization_evidence"]) >= 2, "count": len(out["approval"]["authorization_evidence"])})  # fmt: skip
    # 6. complete CLI path: bundle -> rollback select, real gh, real verifier subprocess
    pol_file = tmp / "policy.json"
    pol_file.write_text(json.dumps(policy()))
    py = [sys.executable, "-m", "dev_platform"]
    env = {
        "PYTHONPATH": str(ROOT / "src"),
        "PATH": subprocess.os.environ["PATH"],
        "HOME": subprocess.os.environ.get("HOME", ""),
    }
    b = subprocess.run(
        [
            *py,
            "evidence",
            "bundle",
            "--out",
            str(tmp / "bundle"),
            "--release",
            str(rel_path),
            "--result",
            str(res_path),
            "--authorization",
            str(bot_file),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    pin = b.stdout.split()[0] if b.returncode == 0 else ""
    pins = ["--app-policy", str(pol_file), "--verifier", str(ROOT / "tools/verify_app_release.py"), "--verifier-sha256", hashlib.sha256((ROOT / "tools/verify_app_release.py").read_bytes()).hexdigest(), "--platform-verifier", str(pv), "--platform-verifier-sha256", hashlib.sha256(pv.read_bytes()).hexdigest()]  # fmt: skip
    r = subprocess.run(
        [
            *py,
            "rollback",
            "select",
            "--application",
            APP,
            "--current",
            "9.9.9",
            "--bundle",
            f"{tmp / 'bundle'}={pin}",
            *pins,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    sel = json.loads(r.stdout) if r.stdout.strip() else {}
    cases.append({"case": "rollback select over a bundle whose only approval is the live web-flow-committed record selects nothing",
                  "ok": b.returncode == 0 and sel.get("eligible") == [] and sel.get("approval_authentication") == "verified" and len(sel.get("rejected", [])) == 1,
                  "rejected": sel.get("rejected"), "exit": r.returncode})  # fmt: skip
    doc = {
        "schema": "dev-platform.live-qualification/v1",
        "repo": a.repo, "identity": BOT, "ran_at": datetime.now(UTC).isoformat(),
        "reaches_approved": False,
        "purpose": "operational (current-state) semantics; one case is historical inspection",
        "limit": "no second GitHub identity with its own signing key exists; the live path therefore never reaches `approved`",
        "fixture_commits": {"bot_signed_web_flow": sha, "unsigned": unsigned_sha,
                            "head_at_end": json.loads(gh("api", f"repos/{a.repo}/commits/main"))["sha"]},
        "release_sha256": records.canonical_digest(rel), "cases": cases, "all_ok": all(c["ok"] for c in cases),
    }  # fmt: skip
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(text)
    print(text)
    return 0 if doc["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
