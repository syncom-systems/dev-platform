#!/usr/bin/env python3
"""Independent verification of a dev-platform release archive.

Deliberately imports nothing from `dev_platform`: it re-implements the digest and structure checks
so that a bug or compromise in the code being released cannot vouch for itself. It relies on the
GitHub CLI (`gh attestation verify`) as the independent signature verifier, then re-checks the
certificate fields against the trust policy itself.

A valid signature is necessary, not sufficient: the signer must match the trust policy (repository,
release workflow, protected version tag, GitHub-hosted runner). When every check passes, a stable release
is `verified` and a pre-release (`-alpha.N`, `-beta.N`, `-rc.N`) is `pre-release`; anything else is `failed`.
The release authority is whoever may push a protected version tag (ADR 0024); no separate approval record
is read. Releases published under a `dev-platform.trust/v1` policy keep their own pinned verifier and
records (`verified-unaccepted`, `accepted`); this verifier refuses such a policy rather than reinterpret it.

Exit status: 0 when every check passed (see `acceptance.state`), 1 otherwise, 2 for an unusable policy.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

RECORD_SCHEMA = "dev-platform.verification/v1"
POLICY_SCHEMA = "dev-platform.trust/v2"
SLSA = "https://slsa.dev/provenance/v1"
CYCLONEDX = "https://cyclonedx.org/bom"
# technical verification passed (trust/v2 `verified`; trust/v1 records said verified-unaccepted or accepted)
VERIFIED_STATES = ("verified", "verified-unaccepted", "accepted")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
GhRunner = Callable[[list[str]], tuple[int, str, str]]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_digest(root: Path) -> str:
    """Same canonical algorithm as dev_platform.digest (re-implemented on purpose)."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            p = Path(dirpath) / name
            if p.is_symlink():
                raise ValueError(f"symlink: {p}")
            entries.append((p.relative_to(root).as_posix(), p.read_bytes()))
    h = hashlib.sha256()
    for rel, data in entries:
        b = rel.encode()
        h.update(len(b).to_bytes(8, "big") + b + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def extract(archive: Path, dest: Path) -> str:
    root = None
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar:
            parts = Path(m.name).parts
            if not (m.isfile() or m.isdir()) or m.name.startswith("/") or ".." in parts or not parts:
                raise ValueError(f"unsafe member {m.name!r}")
            root = root or parts[0]
            if parts[0] != root:
                raise ValueError(f"member {m.name!r} outside root {root!r}")
            target = dest / m.name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())
    if not root or not VERSION_RE.match(root):
        raise ValueError(f"archive root {root!r} is not a version")
    return root


def default_gh(argv: list[str]) -> tuple[int, str, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)
    return r.returncode, r.stdout, r.stderr


class Record:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, cid: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"id": cid, "status": "passed" if ok else "failed", "detail": detail})
        return ok

    @property
    def all_passed(self) -> bool:
        return bool(self.checks) and all(c["status"] == "passed" for c in self.checks)


def check_attestation(
    rec: Record,
    archive: Path,
    archive_sha: str,
    exp: dict,
    policy: dict,
    gh: GhRunner,
    bundle: Path | None,
    *,
    predicate_type: str = SLSA,
    label: str = "attestation",
) -> list[dict]:
    """Verify one attestation type for the archive; returns the results that satisfy the policy."""
    signers = policy.get("signers", [])
    if not rec.add("policy-has-signers", bool(signers), "trust policy must list at least one signer"):
        return []
    ref = exp["ref"]
    matching = [s for s in signers if re.search(s["ref_pattern"], ref)]
    if not rec.add("policy-allows-ref", bool(matching), f"ref {ref} vs policy ref_patterns"):
        return []
    s = matching[0]
    argv = [
        "gh",
        "attestation",
        "verify",
        str(archive),
        "--repo",
        s["repo"],
        "--signer-workflow",
        f"{s['repo']}/{s['workflow']}",
        "--source-digest",
        exp["source_revision"],
        "--source-ref",
        ref,
        "--cert-oidc-issuer",
        policy["oidc_issuer"],
        "--predicate-type",
        predicate_type,
        "--format",
        "json",
    ]
    if policy.get("require_github_hosted_runner"):
        argv.append("--deny-self-hosted-runners")
    if bundle:
        argv += ["--bundle", str(bundle)]
    code, out, err = gh(argv)
    if not rec.add(
        f"{label}-signature", code == 0, "" if code == 0 else (err.strip()[:300] or f"gh exit {code}")
    ):
        return []
    try:
        results = json.loads(out)
    except json.JSONDecodeError:
        rec.add(f"{label}-output", False, "gh output was not JSON")
        return []
    good = []
    for r in results:
        vr = r.get("verificationResult", {})
        cert = vr.get("signature", {}).get("certificate", {})
        stmt = vr.get("statement", {})
        subjects = {d.get("digest", {}).get("sha256") for d in stmt.get("subject", [])}
        problems = []
        if archive_sha not in subjects:
            problems.append("subject digest != archive")
        if stmt.get("predicateType") != predicate_type:
            problems.append("predicate type")
        if cert.get("issuer") != policy["oidc_issuer"]:
            problems.append("issuer")
        if cert.get("sourceRepositoryURI") != f"https://github.com/{s['repo']}":
            problems.append("source repository")
        if cert.get("sourceRepositoryDigest") != exp["source_revision"]:
            problems.append("source revision")
        if cert.get("sourceRepositoryRef") != ref:
            problems.append("source ref")
        signer = cert.get("buildSignerURI", "") or ""
        if not signer.startswith(f"https://github.com/{s['repo']}/{s['workflow']}@"):
            problems.append("signer workflow")
        if policy.get("require_github_hosted_runner") and cert.get("runnerEnvironment") != "github-hosted":
            problems.append("runner environment")
        if not problems:
            good.append(r)
        else:
            rec.add(f"{label}-claim", False, "; ".join(problems))
    rec.add(
        f"{label}-matches-policy",
        bool(good),
        f"{len(good)} attestation(s) satisfy signer policy and expectations",
    )
    return good


def expected_components(toolchains: dict) -> dict:
    """What the SBOM must say about each tool, derived independently from the toolchain manifest."""
    want: dict = {}
    for prof in toolchains["profiles"].values():
        for name, spec in prof["tools"].items():
            c = want.setdefault((name, spec["version"]), {"closure": {}, "source": {}})
            c["closure"].update(spec.get("closure", {}).get("sha256", {}))
            for plat, src in spec.get("source", {}).items():
                if "components" in src:  # one pin per component archive: "<platform>/<archive>"
                    for comp in src["components"]:
                        c["source"][f"{plat}/{comp['archive']}"] = (comp["url"], comp["sha256"])
                else:
                    c["source"][plat] = (src["url"], src["sha256"])
    return want


def sbom_matches_manifest(sbom: dict, toolchains: dict) -> list[str]:
    """Empty list when the SBOM's tool components equal what the manifest declares, exactly."""
    problems = []
    want = expected_components(toolchains)
    have: dict = {}
    for comp in sbom.get("components", []):
        key = (comp.get("name"), comp.get("version"))
        if key in have:
            problems.append(f"duplicate component {key}")
        prefix = "dev-platform:closure-sha256:"
        closure = {
            p["name"][len(prefix) :]: p["value"]
            for p in comp.get("properties", [])
            if p.get("name", "").startswith(prefix)
        }
        source = {
            r["comment"]: (r["url"], r["hashes"][0]["content"])
            for r in comp.get("externalReferences", [])
            if r.get("type") == "distribution"
        }
        have[key] = {"closure": closure, "source": source}
    for key in sorted(set(want) | set(have)):
        if key not in have:
            problems.append(f"missing component {key}")
        elif key not in want:
            problems.append(f"undeclared component {key}")
        elif have[key] != want[key]:
            problems.append(f"component {key} closure/source differ from the manifest")
    return problems


def check_environment(
    rec: Record, env_path: Path | None, manifest: dict | None, exp: dict, policy: dict, gh: GhRunner
) -> None:
    """Release-environment evidence: the record the build produced about its own toolchain."""
    if env_path is None:
        if policy.get("require_environment_evidence", False):
            rec.add("environment-evidence", False, "policy requires the build-environment record")
        return
    try:
        env = json.loads(Path(env_path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        rec.add("environment-evidence", False, f"unreadable: {e}")
        return
    problems = []
    prof = ((manifest or {}).get("profiles") or {}).get(env.get("profile"))
    if prof is None:
        problems.append("profile is not in the release's toolchain manifest")
    if env.get("conformant") is not True or env.get("assurance") != "certifiable":
        problems.append("environment was not conformant and certifiable")
    scope = env.get("scope") or {}
    if scope.get("hermetic") is not False or not scope.get("limitations"):
        problems.append("evidence must state it is not hermetic and list its limitations")
    for t in env.get("tools", []):
        spec = (prof or {}).get("tools", {}).get(t.get("name"))
        pin = ((spec or {}).get("closure") or {}).get("sha256", {}).get(env.get("platform"))
        if (
            t.get("identity") != "closure-verified"
            or not pin
            or (t.get("closure") or {}).get("digest") != pin
        ):
            problems.append(f"tool {t.get('name')}: closure not verified against the manifest pin")
        if spec and t.get("observed") != spec["version"]:
            problems.append(f"tool {t.get('name')}: version differs from the manifest")
    if prof and {t.get("name") for t in env.get("tools", [])} != set(prof["tools"]):
        problems.append("tool set differs from the manifest profile")
    rec.add("environment-evidence", not problems, "; ".join(problems))
    path = Path(env_path)
    check_attestation(rec, path, sha256_file(path), exp, policy, gh, None, label="environment-attestation")


# ---- predecessor continuity ----------------------------------------------------------------------
CONTINUITY_SCHEMA = "dev-platform.continuity/v1"


def check_continuity(
    rec: Record, path: Path | None, exp: dict, archive_sha: str, policy: dict, gh: GhRunner
) -> None:
    """Release N-1 (named and digest-pinned by the policy) verified N's source by running the full stage.
    This is continuity *evidence*: it never grants authority and the operator's pins remain the root of trust.
    A policy that names no predecessor key is a legacy policy; an explicit null predecessor declares a first
    release."""
    if "continuity" not in policy:
        return
    pred = (policy["continuity"] or {}).get("predecessor")
    if pred is None:
        rec.add("continuity", True, "first release: the policy declares no predecessor")
        return
    if path is None:
        rec.add(
            "continuity", False, f"policy names predecessor {pred.get('version')}; continuity record required"
        )
        return
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        rec.add("continuity", False, f"unreadable: {e}")
        return
    problems = []
    if doc.get("schema") != CONTINUITY_SCHEMA:
        problems.append(f"schema must be {CONTINUITY_SCHEMA}")
    subj, p, st = doc.get("subject") or {}, doc.get("predecessor") or {}, doc.get("stage") or {}
    if subj.get("archive_sha256") != archive_sha:
        problems.append("record is about a different archive")
    if subj.get("source_revision") != exp["source_revision"] or st.get("revision") != exp["source_revision"]:
        problems.append("predecessor did not run over this source revision")
    for k in ("version", "archive_sha256", "tree_digest"):
        if p.get(k) != pred.get(k):
            problems.append(f"predecessor {k} differs from the policy pin")
    v = p.get("verification") or {}
    # the predecessor is judged by this verifier (`verified`); the trust/v1 states are accepted for older records
    if v.get("state") not in VERIFIED_STATES or v.get("all_checks_passed") is not True:
        problems.append("predecessor was not itself verified")
    if st.get("name") != "full" or st.get("exit") != 0 or st.get("admission") != "admitted":
        problems.append("predecessor's full stage over this source did not pass")
    rec.add("continuity", not problems, "; ".join(problems))
    path = Path(path)
    check_attestation(rec, path, sha256_file(path), exp, policy, gh, None, label="continuity-attestation")


# ---- identity providers (a library for application-release approvals, ADR 0019) --------------------
# A platform release is NOT judged by approval records (ADR 0024). tools/verify_app_release.py loads the pinned
# platform verifier and authenticates application-release approval records with these providers. A valid
# signature only establishes identity; authority comes from the application's own policy. Unknown providers fail
# closed. The Git author/committer fields on their own are not evidence.
AUTH_SCHEMA = "dev-platform.authorization/v1"
NOT_CONFERRED = [
    "release certification (a property of consumer check results)",
    "qualification of any profile or platform beyond what the release's own qualification evidence shows",
    "approval of any consumer migration or any other release",
]
CLOCK_SKEW = timedelta(minutes=5)
AUTH_PATH_RE = re.compile(r"^authorizations/[A-Za-z0-9._-]+\.json$")


def _api(gh: GhRunner, endpoint: str):
    code, out, err = gh(["gh", "api", endpoint])
    if code != 0:
        raise RuntimeError(f"gh api {endpoint}: {err.strip()[:160] or code}")
    return json.loads(out)


def _login_eq(a: object, b: object) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a != "" and a.lower() == b.lower()


def _auth_github_signed_commit(doc: dict, raw: bytes, auth_policy: dict, gh: GhRunner):
    """Authenticate via GitHub-verified signed commits. Returns (login, evidence) or raises ValueError.

    Every commit that touched the record's path on the pinned ref must carry a signature GitHub reports
    as valid, with author AND committer the same account (a squash/rebase merge makes `web-flow` the
    committer, which proves nothing about the approver). The newest version of the file must be byte-
    identical to the record under review, so a record edited after signing is rejected.
    """
    ia = doc["decided_by"]["identity_assertion"]
    login, path = ia.get("login"), ia.get("path")
    if not isinstance(login, str) or not login:
        raise ValueError("identity_assertion.login required")
    if not isinstance(path, str) or not AUTH_PATH_RE.match(path):
        raise ValueError("identity_assertion.path must be authorizations/<name>.json")
    repo, ref = auth_policy.get("evidence_repo"), auth_policy.get("evidence_ref")
    if not repo or not ref:
        raise ValueError("policy lacks authorization.evidence_repo/evidence_ref")
    try:
        commits = _api(gh, f"repos/{repo}/commits?sha={ref}&path={path}&per_page=100")
    except (RuntimeError, ValueError) as e:
        raise ValueError(f"cannot fetch signing evidence: {e}") from None
    if not isinstance(commits, list) or not commits:
        raise ValueError(f"no commit on {ref} touches {path}")
    if len(commits) >= 100:
        raise ValueError("history of the record is too long to audit")
    for c in commits:
        v = (c.get("commit") or {}).get("verification") or {}
        sha = str(c.get("sha"))[:12]
        if not (v.get("verified") is True and v.get("reason") == "valid"):
            raise ValueError(f"commit {sha} is not a validly signed commit ({v.get('reason')})")
        for role in ("author", "committer"):
            if not _login_eq((c.get(role) or {}).get("login"), login):
                raise ValueError(f"{role} of commit {sha} is not {login}")
    newest = commits[0]
    try:
        blob = _api(gh, f"repos/{repo}/contents/{path}?ref={newest['sha']}")
        content = base64.b64decode(blob["content"])
    except (RuntimeError, ValueError, KeyError) as e:
        raise ValueError(f"cannot read the signed file: {e}") from None
    if content != raw:
        raise ValueError("record differs from the signed file (modified after signing?)")
    return login, {"repo": repo, "ref": ref, "path": path, "commit": newest["sha"], "commits": len(commits)}


def _auth_github_environment_approval(doc: dict, raw: bytes, auth_policy: dict, gh: GhRunner):
    """Authenticate a record produced by a pinned approval workflow after a GitHub Environment approval.

    The record is the attested artifact: `gh attestation verify` must show that exactly these bytes were
    attested by the pinned workflow at the pinned ref, triggered manually (workflow_dispatch), on a
    GitHub-hosted runner. The workflow wrote `login` from the run's recorded approval, so the approver is
    whoever GitHub says clicked Approve; the committer of the file in the repository proves nothing here.
    """
    ia = doc["decided_by"]["identity_assertion"]
    login, path = ia.get("login"), ia.get("path")
    if not isinstance(login, str) or not login:
        raise ValueError("identity_assertion.login required")
    if not isinstance(path, str) or not AUTH_PATH_RE.match(path):
        raise ValueError("identity_assertion.path must be authorizations/<name>.json")
    ep = auth_policy.get("environment_approval")
    if not isinstance(ep, dict) or not all(
        isinstance(ep.get(k), str) and ep[k] for k in ("repo", "workflow", "ref")
    ):
        raise ValueError("policy lacks authorization.environment_approval {repo, workflow, ref}")
    issuer = "https://token.actions.githubusercontent.com"
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "record.json"
        f.write_bytes(raw)
        code, out, err = gh(
            [
                "gh",
                "attestation",
                "verify",
                str(f),
                "--repo",
                ep["repo"],
                "--signer-workflow",
                f"{ep['repo']}/{ep['workflow']}",
                "--source-ref",
                ep["ref"],
                "--cert-oidc-issuer",
                issuer,
                "--predicate-type",
                SLSA,
                "--deny-self-hosted-runners",
                "--format",
                "json",
            ]
        )
    if code != 0:
        raise ValueError(f"no valid attestation for this record: {err.strip()[:200] or code}")
    try:
        results = json.loads(out)
    except json.JSONDecodeError:
        raise ValueError("gh output was not JSON") from None
    digest = hashlib.sha256(raw).hexdigest()
    for r in results:
        vr = r.get("verificationResult", {})
        cert = vr.get("signature", {}).get("certificate", {})
        stmt = vr.get("statement", {})
        subjects = {d.get("digest", {}).get("sha256") for d in stmt.get("subject", [])}
        signer = cert.get("buildSignerURI", "") or ""
        if (
            digest in subjects
            and stmt.get("predicateType") == SLSA
            and cert.get("issuer") == issuer
            and cert.get("sourceRepositoryURI") == f"https://github.com/{ep['repo']}"
            and cert.get("sourceRepositoryRef") == ep["ref"]
            and signer.startswith(f"https://github.com/{ep['repo']}/{ep['workflow']}@")
            and cert.get("buildTrigger") == "workflow_dispatch"
            and cert.get("runnerEnvironment") == "github-hosted"
        ):
            return login, {
                "repo": ep["repo"],
                "workflow": ep["workflow"],
                "ref": ep["ref"],
                "run": cert.get("runInvocationURI"),
                "source_digest": cert.get("sourceRepositoryDigest"),
            }
    raise ValueError("attestation does not match the pinned approval workflow, ref, trigger and runner")


PROVIDERS = {
    "github-signed-commit": _auth_github_signed_commit,
    "github-environment-approval": _auth_github_environment_approval,
}  # the explicit registry; unknown = refused


def _ts(v: object) -> datetime:
    if not isinstance(v, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(UTC)


def verify(
    archive: Path,
    exp: dict,
    policy: dict,
    *,
    gh: GhRunner = default_gh,
    authorizations: list[Path] = (),
    bundle: Path | None = None,
    sbom_bundle: Path | None = None,
    environment: Path | None = None,
    continuity: Path | None = None,
    now: datetime | None = None,
) -> dict:
    # `authorizations` and `now` are accepted from callers written for trust/v1 verifiers and are not evaluated:
    # a platform release has no approval record (ADR 0024).
    del authorizations, now
    rec = Record()
    rec.add("policy-schema", policy.get("schema") == POLICY_SCHEMA,
            f"policy must be {POLICY_SCHEMA}; a trust/v1 release is verified by the verifier pinned with it")  # fmt: skip
    sbom_doc = None
    manifest = None
    archive_sha = sha256_file(archive)
    rec.add("archive-digest", archive_sha == exp["archive_sha256"], f"actual {archive_sha}")
    subject = {"archive": archive.name, "archive_sha256": archive_sha, "tree_digest": None, "version": None}
    with tempfile.TemporaryDirectory(prefix="verify-release-") as tmp:
        try:
            root = extract(archive, Path(tmp))
        except (ValueError, tarfile.TarError, OSError) as e:
            rec.add("safe-extract", False, str(e))
            root = None
        if root:
            rec.add("safe-extract", True)
            d = Path(tmp) / root
            subject["version"] = root
            subject["tree_digest"] = tree_digest(d)
            rec.add(
                "version-binding", root == exp["version"], f"archive root {root}, expected {exp['version']}"
            )
            try:
                rel = json.loads((d / "release.json").read_text())
            except (OSError, json.JSONDecodeError) as e:
                rec.add("release-json", False, str(e))
                rel = None
            if rel is not None:
                manifest = rel.get("toolchains")
                rec.add("release-json", rel.get("schema") == "dev-platform.release/v1")
                rec.add("release-version", rel["platform"]["version"] == exp["version"])
                rec.add("source-digest", tree_digest(d / "src") == rel["platform"]["source_digest"])
                init = (d / "src" / "dev_platform" / "__init__.py").read_text()
                m = re.search(r'^__version__ = "([^"]+)"', init, re.M)
                rec.add("source-version-matches", bool(m) and m.group(1) == exp["version"])
                rec.add(
                    "source-revision",
                    rel["provenance"].get("source_revision") == exp["source_revision"],
                    f"release.json says {rel['provenance'].get('source_revision')}",
                )
                sbom_path = d / rel["sbom"]["path"]
                sbom_ok = sbom_path.is_file() and sha256_file(sbom_path) == rel["sbom"]["sha256"]
                rec.add("sbom-digest", sbom_ok)
                if sbom_ok:
                    names = {
                        (c["name"], c["version"])
                        for c in json.loads(sbom_path.read_text()).get("components", [])
                    }
                    need = {
                        (t, spec["version"])
                        for p in rel["toolchains"]["profiles"].values()
                        for t, spec in p["tools"].items()
                    }
                    rec.add("sbom-covers-toolchains", need <= names, f"missing {sorted(need - names)}")
                    sbom_doc = json.loads(sbom_path.read_text())
                    mism = sbom_matches_manifest(sbom_doc, rel["toolchains"])
                    rec.add("sbom-matches-manifest", not mism, "; ".join(mism))
                    rec.add(
                        "sbom-describes-artifact",
                        sbom_doc.get("metadata", {}).get("component", {}).get("version") == exp["version"]
                        and any(
                            h.get("content") == rel["platform"]["source_digest"]
                            for h in sbom_doc["metadata"]["component"].get("hashes", [])
                        ),
                        "SBOM root component must be this version and source digest",
                    )
                if exp.get("tree_digest"):
                    rec.add("tree-digest", subject["tree_digest"] == exp["tree_digest"])
    check_attestation(rec, archive, archive_sha, exp, policy, gh, bundle)
    attested = check_attestation(
        rec,
        archive,
        archive_sha,
        exp,
        policy,
        gh,
        sbom_bundle,
        predicate_type=CYCLONEDX,
        label="sbom-attestation",
    )
    rec.add(
        "sbom-attestation-content",
        sbom_doc is not None
        and any(
            r.get("verificationResult", {}).get("statement", {}).get("predicate") == sbom_doc
            for r in attested
        ),
        "the attested SBOM must be exactly the SBOM inside the archive",
    )

    check_environment(rec, environment, manifest, exp, policy, gh)
    check_continuity(rec, continuity, exp, archive_sha, policy, gh)
    if not rec.all_passed:
        state, reasons = "failed", [c["id"] for c in rec.checks if c["status"] == "failed"]
    elif "-" in exp["version"]:
        state, reasons = (
            "pre-release",
            ["pre-release version: verified artifacts, published as a pre-release"],
        )
    else:
        state, reasons = "verified", ["every check passed for a release built from a protected version tag"]
    return {
        "schema": RECORD_SCHEMA,
        "subject": subject,
        "expected": {k: v for k, v in exp.items()},
        "policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
        "checks": rec.checks,
        "acceptance": {"state": state, "reasons": reasons, "not_conferred": NOT_CONFERRED},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archive", type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--source-revision", required=True, help="expected full git commit sha")
    ap.add_argument("--archive-sha256", required=True)
    ap.add_argument("--tree-digest")
    ap.add_argument("--ref", help="expected git ref (default refs/tags/v<version>)")
    ap.add_argument("--policy", type=Path, required=True, help="trust policy (from outside the release)")
    ap.add_argument("--bundle", type=Path, help="offline provenance attestation bundle")
    ap.add_argument("--sbom-bundle", type=Path, help="offline SBOM attestation bundle")
    ap.add_argument("--environment", type=Path, help="release build-environment record (attested)")
    ap.add_argument("--continuity", type=Path, help="predecessor continuity record (attested)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    policy = json.loads(a.policy.read_text())
    if policy.get("schema") != POLICY_SCHEMA:
        print(f"policy schema must be {POLICY_SCHEMA} (a trust/v1 release is verified by the verifier pinned "
              "with its policy)", file=sys.stderr)  # fmt: skip
        return 2
    exp = {
        "version": a.version,
        "source_revision": a.source_revision,
        "archive_sha256": a.archive_sha256,
        "ref": a.ref or f"refs/tags/v{a.version}",
    }
    if a.tree_digest:
        exp["tree_digest"] = a.tree_digest
    doc = verify(
        a.archive,
        exp,
        policy,
        bundle=a.bundle,
        sbom_bundle=a.sbom_bundle,
        environment=a.environment,
        continuity=a.continuity,
    )
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(text)
    for c in doc["checks"]:
        print(
            f"{c['status'].upper():7} {c['id']}"
            + (f"  ({c['detail']})" if c["detail"] and c["status"] == "failed" else "")
        )
    print(f"acceptance: {doc['acceptance']['state']}  {'; '.join(doc['acceptance']['reasons'])}")
    return 0 if doc["acceptance"]["state"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
