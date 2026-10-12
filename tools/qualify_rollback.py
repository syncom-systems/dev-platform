#!/usr/bin/env python3
"""Rollback eligibility through the COMPLETE evidence path, with must-be-refused cases (v0.3.x).

Everything runs the shipped code end to end: releases assembled by `dev-platform provenance assemble`, write-once
bundles by `dev-platform evidence bundle`, selection by `dev-platform rollback select` with every verifier pinned,
approvals judged by the independent verifier in a subprocess. The only double is the `gh` executable on PATH
(`bin/gh`, a recording of GitHub's commit/contents answers); the verifier code under test cannot tell the difference.

A release is selectable only if it is an exact, bundled, authenticated, authorized, in-force approved release with
no advisory against it. Each refusal below names its reason; none may appear under `eligible`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIM = """#!/usr/bin/env python3
import json, os, sys
sys.path.insert(0, {tools!r})
from qualify_app_release import RecordedGitHub
if os.environ.get("QUAL_GH_OUTAGE"):
    sys.stderr.write("HTTP 502: Bad Gateway"); sys.exit(1)
code, out, err = RecordedGitHub.load(os.environ["QUAL_GH_HISTORY"])(["gh", *sys.argv[1:]])
sys.stdout.write(out); sys.stderr.write(err); sys.exit(code)
"""


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def install_shim(work: Path) -> Path:
    b = work / "bin"
    b.mkdir(parents=True, exist_ok=True)
    g = b / "gh"
    g.write_text(SHIM.format(tools=str(ROOT / "tools")))
    g.chmod(g.stat().st_mode | stat.S_IXUSR)
    return b


def run(
    *, env: dict, work: Path, result_path: Path, assemble, approval, double, policy: dict, app: str
) -> dict:
    """`assemble(version) -> release dict`; `approval(name, release, **over) -> record dict`; `double`: RecordedGitHub."""
    work = work / "rollback"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    shim = install_shim(work)
    hist = work / "gh-history.json"
    senv = {**env, "PATH": f"{shim}{os.pathsep}{env.get('PATH', '')}", "QUAL_GH_HISTORY": str(hist)}
    py = [sys.executable, "-m", "dev_platform"]
    pol = work / "app-policy.json"
    pol.write_text(json.dumps(policy, sort_keys=True))
    pins = [
        "--app-policy", str(pol),
        "--verifier", str(ROOT / "tools/verify_app_release.py"),
        "--verifier-sha256", _sha(ROOT / "tools/verify_app_release.py"),
        "--platform-verifier", str(ROOT / "tools/verify_release.py"),
        "--platform-verifier-sha256", _sha(ROOT / "tools/verify_release.py"),
    ]  # fmt: skip
    res_path = work / "result.json"

    def cli(*argv, check=False):
        double.dump(hist)
        return subprocess.run([*py, *argv], cwd=ROOT, env=senv, capture_output=True, text=True)

    def write(name, doc) -> Path:
        p = work / name
        p.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
        return p

    releases: dict[str, dict] = {}
    bundles: dict[str, tuple[Path, str]] = {}

    def release(v):
        if v not in releases:
            releases[v] = assemble(v)
        return releases[v]

    def sign(v, name, **over):
        """A record about release v, committed 'by' the approver (or as overridden) in the double."""
        sign_kw = over.pop("sign", {})
        doc = approval(name, release(v), **over)
        p = write(f"{name}.json", doc)
        double.sign(f"authorizations/{name}.json", p.read_bytes(), **sign_kw)
        return p

    def bundle(v, auths, *, advisories=(), previous=None, label=None):
        out = work / f"bundle-{label or v}"
        rp = write(f"release-{v}.json", release(v))
        cmd = ["evidence", "bundle", "--out", str(out), "--release", str(rp), "--result", str(res_path)]
        for a in auths:
            cmd += ["--authorization", str(a)]
        for a in advisories:
            cmd += ["--advisory", str(a)]
        if previous:
            cmd += ["--previous", previous]
        r = cli(*cmd)
        if r.returncode:
            raise RuntimeError(f"bundle {v}: {r.stderr[-300:]}")
        pin = r.stdout.split()[0]
        bundles[label or v] = (out, pin)
        return out, pin

    def select(labels, *extra, current="9.9.9", pinned=True):
        argv = ["rollback", "select", "--application", app, "--current", current]
        for lb in labels:
            d, pin = bundles[lb]
            argv += ["--bundle", f"{d}={pin}"]
        argv += [*(pins if pinned else []), *extra]
        r = cli(*argv)
        try:
            out = json.loads(r.stdout) if r.stdout.strip() else None
        except ValueError:
            out = None
        return r.returncode, out, r.stderr

    cases: list[dict] = []

    def record(name, ok, detail):
        cases.append({"case": name, "ok": bool(ok), "detail": detail})

    def reasons(out, v):
        return next((r["reasons"] for r in (out or {}).get("rejected", []) if r["version"] == v), None)

    def eligible(out):
        return [e["version"] for e in (out or {}).get("eligible", [])]

    shutil.copy(result_path, res_path)
    adv = lambda name, comp, vers: write(  # noqa: E731
        name, {"schema": "dev-platform.advisory/v1", "id": name.removesuffix(".json").upper(), "summary": "qualification advisory",
               "severity": "high", "affected": [{"component": comp, "versions": vers}]})  # fmt: skip
    T = "2026-10-11T10:00:00Z"
    rev_of = lambda v, n: sign(v, n, decision="revoked", decided_at=T)  # noqa: E731

    # --- one selection over releases in every state --------------------------------------------------------
    bundle("1.0.0", [sign("1.0.0", "ok-100")])
    bundle("1.1.0", [sign("1.1.0", "ok-110"), rev_of("1.1.0", "rev-110")])
    bundle("1.2.0", [sign("1.2.0", "ok-120"),
                     sign("1.2.0", "sup-120", decision="rejected", decided_at=T, supersedes=["ok-120"])])  # fmt: skip
    bundle("1.3.0", [sign("1.3.0", "ok-130")], advisories=[adv("adv-app.json", app, ["1.3.0"])])
    stranger = {"id": "rm", "role": "release-approver", "identity_assertion": {
        "provider": "github-signed-commit", "login": "qualify-stranger", "path": "authorizations/ok-150.json"}}  # fmt: skip
    bundle("1.5.0", [sign("1.5.0", "ok-150", decided_by=stranger,
                          sign={"author": "qualify-stranger", "committer": "qualify-stranger"})])  # fmt: skip
    bundle("1.6.0", [sign("1.6.0", "ok-160", sign={"verified": False})])
    p170 = sign("1.7.0", "ok-170")
    p170.write_text(p170.read_text().replace("qualification", "edited-after-signing"))
    # the edit also reaches the evidence repository, as an unsigned commit (the genuine signed copy is then history)
    double.commit({"authorizations/ok-170.json": p170.read_bytes()}, verified=False, author="qualify-approver",
                  committer="qualify-approver")  # fmt: skip
    bundle("1.7.0", [p170])
    code, out, _ = select(["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.5.0", "1.6.0", "1.7.0"])
    record("only the authenticated, unrevoked, unsuperseded, unaffected release is eligible",
           eligible(out) == ["1.0.0"] and out["approval_authentication"] == "verified" and code == 0,
           {"eligible": eligible(out), "exit": code})  # fmt: skip
    for v, needle, label in (
        ("1.1.0", "authentic revoked", "revoked release is refused"),
        ("1.2.0", "authentic rejected", "superseded approval (decision replaced) is refused"),
        ("1.3.0", "ADV-APP", "release with an advisory against it is refused"),
        ("1.5.0", "not an approver", "approval by an authenticated non-approver is refused"),
        ("1.6.0", "not a validly signed", "unsigned approval is refused"),
        (
            "1.7.0",
            "not a validly signed",
            "approval edited in the evidence repository after signing is refused",
        ),
    ):
        r = reasons(out, v)
        record(label, r is not None and v not in eligible(out) and needle in " ".join(r), r)
    # --- platform advisory: the release is refused when its Dev Platform release is affected -----------------
    plat_v = release("1.0.0")["platform"]["release_version"]
    bundle(
        "1.4.0",
        [sign("1.4.0", "ok-140")],
        advisories=[adv("adv-platform.json", "dev-platform", [plat_v])],
        label="1.4.0-adv",
    )
    code, out, _ = select(["1.0.0", "1.4.0-adv"])
    record("advisory on the Dev Platform release refuses every release built with it",
           eligible(out) == [] and {r["version"] for r in out["rejected"]} == {"1.0.0", "1.4.0"},
           {"eligible": eligible(out), "rejected": [r["version"] for r in out["rejected"]]})  # fmt: skip
    # --- tampered bundle aborts selection; nothing from it is used ------------------------------------------
    d, _ = bundles["1.0.0"]
    target = d / "release.json"
    target.chmod(0o600)
    target.write_text(target.read_text() + " ")
    code, out, err = select(["1.0.0"])
    record(
        "tampered bundle (byte appended after pinning) aborts selection",
        code != 0 and out is None,
        err.strip()[:200],
    )
    # --- wrong pins ------------------------------------------------------------------------------------------
    code, out, err = select(["1.1.0"], pinned=False)
    record("selection without the pinned verifiers is refused", code != 0 and out is None, err.strip()[:160])
    wrong = [("0" * 64 if a == pins[pins.index("--verifier-sha256") + 1] else a) for a in pins]
    argv = ["rollback", "select", "--application", app, "--current", "9.9.9", *wrong]
    r = cli(*argv)
    record(
        "selection with a wrong verifier pin is refused",
        r.returncode != 0 and not r.stdout.strip(),
        r.stderr.strip()[:160],
    )
    # --- unbundled (not immutable) / insufficient evidence ----------------------------------------------------
    rp = write("loose-release.json", release("1.0.0"))
    ap = sign("1.0.0", "ok-100-loose")
    r = cli("rollback", "select", "--application", app, "--current", "9.9.9", "--release", str(rp), "--result", str(res_path),
            "--authorization", str(ap), *pins)  # fmt: skip
    out = json.loads(r.stdout) if r.stdout.strip() else None
    record(
        "release record outside any pinned bundle is not an immutable target",
        eligible(out) == [] and "not immutable" in " ".join(reasons(out, "1.0.0") or []),
        reasons(out, "1.0.0"),
    )
    r = cli("rollback", "select", "--application", app, "--current", "9.9.9", "--allow-unbundled", "--release", str(rp),
            "--authorization", str(ap), *pins)  # fmt: skip
    out = json.loads(r.stdout) if r.stdout.strip() else None
    record(
        "approval without the verification evidence is refused (insufficiently verified)",
        eligible(out) == [] and any("verification-evidence" in x for x in reasons(out, "1.0.0") or []),
        reasons(out, "1.0.0"),
    )
    # --- freshness: current-state authorization is mandatory for a rollback decision ------------------------
    bundle("1.8.0", [sign("1.8.0", "ok-180")])
    code, before, _ = select(["1.8.0"])
    record("approval with nothing newer in the evidence repository is eligible (current state read live)",
           eligible(before) == ["1.8.0"] and before["authorization_state"] == "current"
           and before["eligible"][0]["currency"]["status"] == "current", eligible(before))  # fmt: skip
    rev_of("1.8.0", "rev-180")  # published after the bundle was written; no bundle contains it
    code, fresh, _ = select(["1.8.0"])
    record(
        "a revocation published independently, absent from the pinned bundle, refuses the release",
        eligible(fresh) == [] and reasons(fresh, "1.8.0") is not None,
        reasons(fresh, "1.8.0"),
    )
    bundle("1.9.0", [sign("1.9.0", "ok-190")])
    senv["QUAL_GH_OUTAGE"] = "1"
    try:
        code, out, _ = select(["1.9.0"])
    finally:
        del senv["QUAL_GH_OUTAGE"]
    record(
        "evidence repository unreachable: nothing is eligible (current state unverifiable, fail closed)",
        eligible(out) == [] and any("authorization-currency" in x for x in reasons(out, "1.9.0") or []),
        reasons(out, "1.9.0"),
    )
    rev_of("1.9.0", "rev-190")
    double.delete("authorizations/rev-190.json", author="intruder", committer="intruder")
    code, out, _ = select(["1.9.0"])
    record(
        "a revocation deleted from the evidence history is not silently absent: release refused",
        eligible(out) == []
        and any("deleted from the evidence history" in x for x in reasons(out, "1.9.0") or []),
        reasons(out, "1.9.0"),
    )
    return {"cases": cases, "all_ok": all(c["ok"] for c in cases)}
