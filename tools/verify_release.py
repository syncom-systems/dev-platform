#!/usr/bin/env python3
"""Independent verification of a dev-platform release archive.

Deliberately imports nothing from `dev_platform`: it re-implements the digest and structure checks
so that a bug or compromise in the code being released cannot vouch for itself. It relies on the
GitHub CLI (`gh attestation verify`) as the independent signature verifier, then re-checks the
certificate fields against the trust policy itself.

A valid signature is necessary, not sufficient: the signer must match the trust policy, and a
*stable* release is only `accepted` with an effective owner authorization for the archive digest.
Pre-releases are never `accepted`.

Exit status: 0 when every check passed (see `acceptance.state`), 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

RECORD_SCHEMA = "dev-platform.verification/v1"
POLICY_SCHEMA = "dev-platform.trust/v1"
SLSA = "https://slsa.dev/provenance/v1"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
UNTRUSTED_PROVIDERS = {"git-commit-author", "git-config"}  # authorship is not approval
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
    rec: Record, archive: Path, archive_sha: str, exp: dict, policy: dict, gh: GhRunner, bundle: Path | None
) -> None:
    signers = policy.get("signers", [])
    if not rec.add("policy-has-signers", bool(signers), "trust policy must list at least one signer"):
        return
    ref = exp["ref"]
    matching = [s for s in signers if re.search(s["ref_pattern"], ref)]
    if not rec.add("policy-allows-ref", bool(matching), f"ref {ref} vs policy ref_patterns"):
        return
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
        "--format",
        "json",
    ]
    if policy.get("require_github_hosted_runner"):
        argv.append("--deny-self-hosted-runners")
    if bundle:
        argv += ["--bundle", str(bundle)]
    code, out, err = gh(argv)
    if not rec.add(
        "attestation-signature", code == 0, "" if code == 0 else (err.strip()[:300] or f"gh exit {code}")
    ):
        return
    try:
        results = json.loads(out)
    except json.JSONDecodeError:
        rec.add("attestation-output", False, "gh output was not JSON")
        return
    good = []
    for r in results:
        vr = r.get("verificationResult", {})
        cert = vr.get("signature", {}).get("certificate", {})
        stmt = vr.get("statement", {})
        subjects = {d.get("digest", {}).get("sha256") for d in stmt.get("subject", [])}
        problems = []
        if archive_sha not in subjects:
            problems.append("subject digest != archive")
        if stmt.get("predicateType") != SLSA:
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
            rec.add("attestation-claim", False, "; ".join(problems))
    rec.add(
        "attestation-matches-policy",
        bool(good),
        f"{len(good)} attestation(s) satisfy signer policy and expectations",
    )


def effective_authorization(paths: list[Path], archive_sha: str) -> dict | None:
    docs = [json.loads(Path(p).read_text()) for p in paths]
    mine = [
        d
        for d in docs
        if d.get("schema") == "dev-platform.authorization/v1"
        and d.get("subject", {}).get("kind") == "platform-release"
        and d.get("subject", {}).get("digest") == archive_sha
    ]
    superseded = {s for d in mine for s in d.get("supersedes", [])}
    live = sorted((d for d in mine if d["id"] not in superseded), key=lambda d: d["decided_at"])
    if not live or live[-1]["decision"] != "approved":
        return None
    ia = live[-1].get("decided_by", {}).get("identity_assertion", {})
    if not ia.get("provider") or not ia.get("reference") or ia["provider"] in UNTRUSTED_PROVIDERS:
        return None
    return live[-1]


def verify(
    archive: Path,
    exp: dict,
    policy: dict,
    *,
    gh: GhRunner = default_gh,
    authorizations: list[Path] = (),
    bundle: Path | None = None,
) -> dict:
    rec = Record()
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
                if exp.get("tree_digest"):
                    rec.add("tree-digest", subject["tree_digest"] == exp["tree_digest"])
    check_attestation(rec, archive, archive_sha, exp, policy, gh, bundle)

    prerelease = "-" in exp["version"]
    auth = None if prerelease else effective_authorization(list(authorizations), archive_sha)
    if not rec.all_passed:
        state, reasons = "failed", [c["id"] for c in rec.checks if c["status"] == "failed"]
    elif prerelease:
        state, reasons = "pre-release", ["pre-releases are never accepted; they are verified artifacts only"]
    elif policy.get("stable_requires_authorization", True) and auth is None:
        state, reasons = "verified-unaccepted", ["no effective owner authorization for this archive digest"]
    else:
        state, reasons = (
            "accepted",
            [f"owner authorization {auth['id']}" if auth else "policy does not require authorization"],
        )
    return {
        "schema": RECORD_SCHEMA,
        "subject": subject,
        "expected": {k: v for k, v in exp.items()},
        "policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
        "checks": rec.checks,
        "acceptance": {"state": state, "reasons": reasons, "authorization": auth["id"] if auth else None},
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
    ap.add_argument("--authorization", type=Path, action="append", default=[])
    ap.add_argument("--bundle", type=Path, help="offline attestation bundle")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    policy = json.loads(a.policy.read_text())
    if policy.get("schema") != POLICY_SCHEMA:
        print(f"policy schema must be {POLICY_SCHEMA}", file=sys.stderr)
        return 2
    exp = {
        "version": a.version,
        "source_revision": a.source_revision,
        "archive_sha256": a.archive_sha256,
        "ref": a.ref or f"refs/tags/v{a.version}",
    }
    if a.tree_digest:
        exp["tree_digest"] = a.tree_digest
    doc = verify(a.archive, exp, policy, authorizations=a.authorization, bundle=a.bundle)
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
