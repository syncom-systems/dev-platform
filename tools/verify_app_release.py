#!/usr/bin/env python3
"""Independent verification of one application release (ADR 0019).

Imports nothing from `dev_platform`. It re-derives every binding itself and authenticates the approval with
the identity-provider registry of the (separately pinned) platform verifier `tools/verify_release.py`, so the
provider model of ADR 0016 is reused, not duplicated.

Questions, each answered separately and failing closed:
  binding       the release record's source revision, dependency state, Dev Platform release, toolchain identity,
                verification results and artifact digests are exactly what the operator supplied and pinned
  eligibility   the platform release is allowed by the APPLICATION policy (not by platform acceptance, which is a
                different decision about a different subject) and no supplied advisory affects it or the application
  authenticity  who made each authorization record (provider evidence verified here, never read from the record)
  authority     may that identity approve THIS application, conferring THIS claim (application policy)
  validity      in force now; supersession and revocation count only when authenticated and authorized

`--mode release` needs the lock files, artifact bytes and the source-revision pin and verifies them. `--mode select`
(rollback) re-derives everything that digests alone can establish and reports the rest under
`coverage.not_evaluated`: it is weaker, and says so.

Two purposes, never mixed up. The default, `operational`, is a CURRENT decision (deploy, release eligibility,
rollback): the authorization state is read from the evidence repository at one commit (every record, a revocation
nobody supplied included), the history is audited for deleted records, and anything that cannot be established
(unreachable, truncated, moved while reading, a failed call) makes the decision `failed`. `--historical` inspects only
the supplied records, looks for nothing newer, and can never yield `approved`.

Exit status: 0 when state is `approved`; 1 when `failed`; 3 when `unapproved`; 4 when `historical-approval`
(authentic once, not a current authorization); 2 on bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RECORD_SCHEMA = "dev-platform.app-release-verification/v1"
POLICY_SCHEMA = "dev-platform.app-trust/v1"
PURPOSES = ("operational", "historical")
APP_RELEASE = "dev-platform.app-release/v1"
AUTH_SCHEMA = "dev-platform.authorization/v1"
RESULT_SCHEMA = "dev-platform.result/v1"
ADVISORY = "dev-platform.advisory/v1"
CONFERABLE_CLAIMS = {"application-release-approval"}  # the ONLY claim an application approval can confer
NOT_CONFERRED = [
    "platform release acceptance (a separate decision about a separate subject)",
    "deployment, promotion or rollout authorization",
    "regulated release approval or any compliance claim",
    "approval of any other application release",
]
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REV = re.compile(r"^[0-9a-f]{40}$")
_RANGE = re.compile(r"^(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)$")


def load_platform_verifier(path: Path, pin: str):
    """The provider registry lives in tools/verify_release.py; its bytes must match the operator's pin."""
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if got != pin:
        raise SystemExit(f"verify_release.py sha256 {got} does not match the pin {pin}")
    spec = importlib.util.spec_from_file_location("_pinned_verify_release", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def canonical_digest(doc: object) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolution_digest(files: list[Path], root: Path) -> str:
    """Names and bytes of the dependency-resolution inputs, order-independent (same algorithm as the platform)."""
    h = hashlib.sha256()
    root = Path(root).resolve()
    items = sorted((Path(f).resolve().relative_to(root).as_posix(), Path(f)) for f in files)
    for rel, f in items:
        name, data = rel.encode(), f.read_bytes()
        h.update(len(name).to_bytes(8, "big") + name + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


class Record:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, cid: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"id": cid, "status": "passed" if ok else "failed", "detail": detail})
        return ok

    @property
    def all_passed(self) -> bool:
        return all(c["status"] == "passed" for c in self.checks)


# ---------------------------------------------------------------- shape


def release_shape_problems(d: object) -> list[str]:
    if not isinstance(d, dict) or d.get("schema") != APP_RELEASE:
        return [f"schema must be {APP_RELEASE}"]
    p: list[str] = []

    def sec(name: str, keys: list[str]) -> dict:
        s = d.get(name)
        if not isinstance(s, dict):
            p.append(f"{name}: object required")
            return {}
        p.extend(f"{name}.{k}: required string" for k in keys if not (isinstance(s.get(k), str) and s[k]))
        return s

    sec("application", ["name", "version"])
    src = sec("source", ["uri", "revision"])
    if isinstance(src.get("revision"), str) and not _REV.match(src["revision"]):
        p.append("source.revision: 40 lowercase hex characters (a full commit id)")
    dep = sec("dependencies", ["resolution_digest"])
    plat = sec("platform", ["release_version", "release_tree_digest", "profile", "toolchain_identity_digest"])
    for where, v in (
        ("dependencies.resolution_digest", dep.get("resolution_digest")),
        ("platform.release_tree_digest", plat.get("release_tree_digest")),
        ("platform.toolchain_identity_digest", plat.get("toolchain_identity_digest")),
    ):
        if not (isinstance(v, str) and _SHA.match(v)):
            p.append(f"{where}: 64 lowercase hex characters")
    for key, kind in (("artifacts", "name"), ("evidence", "kind")):
        items = d.get(key)
        if not (isinstance(items, list) and items):
            p.append(f"{key}: at least one entry required")
            continue
        for i, it in enumerate(items):
            if not (isinstance(it, dict) and isinstance(it.get(kind), str) and it[kind]):
                p.append(f"{key}[{i}].{kind}: required")
            elif not (isinstance(it.get("sha256"), str) and _SHA.match(it["sha256"])):
                p.append(f"{key}[{i}].sha256: 64 lowercase hex characters")
    names = [a.get("name") for a in d.get("artifacts") or [] if isinstance(a, dict)]
    if len(names) != len(set(names)):
        p.append("artifacts: duplicate names")
    return p


def policy_problems(policy: object) -> list[str]:
    if not isinstance(policy, dict) or policy.get("schema") != POLICY_SCHEMA:
        return [f"policy schema must be {POLICY_SCHEMA}"]
    p: list[str] = []
    auth = policy.get("authorization")
    if not isinstance(auth, dict):
        return ["policy.authorization: object required"]
    for k in ("evidence_repo", "evidence_ref"):
        if not (isinstance(auth.get(k), str) and auth[k]):
            p.append(f"policy.authorization.{k}: required")
    if not (isinstance(auth.get("providers"), list) and auth["providers"]):
        p.append("policy.authorization.providers: non-empty list required")
    if not isinstance(auth.get("approvers"), list):
        p.append("policy.authorization.approvers: list required")
    fr = policy.get("freshness")
    if fr is not None:
        age = fr.get("max_age_seconds") if isinstance(fr, dict) else None
        if not (isinstance(age, int) and not isinstance(age, bool) and 1 <= age <= MAX_AGE_CAP):
            p.append(f"policy.freshness.max_age_seconds: integer 1..{MAX_AGE_CAP} required")
    pr = policy.get("platform_releases")
    if not (isinstance(pr, list) and pr):
        p.append("policy.platform_releases: the Dev Platform releases this application accepts (non-empty)")
    else:
        for i, e in enumerate(pr):
            if not (isinstance(e, dict) and e.get("version") and _SHA.match(str(e.get("tree_digest")))):
                p.append(f"policy.platform_releases[{i}]: version and tree_digest required")
            elif e.get("require_acceptance") is not None:
                if e["require_acceptance"] is not True:
                    p.append(f"policy.platform_releases[{i}].require_acceptance: only true is meaningful")
                elif not (
                    _SHA.match(str(e.get("archive_sha256"))) and _REV.match(str(e.get("source_revision")))
                ):
                    p.append(
                        f"policy.platform_releases[{i}]: require_acceptance needs archive_sha256 and source_revision"
                    )
    return p


# ---------------------------------------------------------------- results (verification evidence)


def result_problems(res: dict, rel: dict) -> list[str]:
    """Why a result cannot back this release (empty when it can)."""
    p: list[str] = []
    cert = res.get("certification") or {}
    env = res.get("environment") or {}
    if res.get("schema") != RESULT_SCHEMA:
        return [f"not a {RESULT_SCHEMA} record"]
    if res.get("stage") != "full" or not res.get("executed"):
        p.append("not an executed full-stage run")
    if cert.get("certified") is not True:
        p.append("not certified")
    if (res.get("platform") or {}).get("mode") != "pinned":
        p.append("platform was not a pinned release")
    if env.get("assurance") != "certifiable":
        p.append("environment is not certifiable")
    pl = rel["platform"]
    for got, want, what in (
        (res.get("revision"), rel["source"]["revision"], "source revision"),
        (env.get("identity_digest"), pl["toolchain_identity_digest"], "toolchain identity"),
        ((env.get("release") or {}).get("tree_digest"), pl["release_tree_digest"], "platform tree digest"),
        ((env.get("release") or {}).get("version"), pl["release_version"], "platform release version"),
        (env.get("profile"), pl["profile"], "profile"),
    ):
        if got != want:
            p.append(f"{what} differs from the release")
    return p


# ---------------------------------------------------------------- advisories


def _vtuple(v: str):
    m = re.match(r"^v?(\d+(?:\.\d+)*)", str(v))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _in_range(version: str, spec: str) -> bool:
    """Every constraint holds; anything unparsable counts as affected (fail closed)."""
    have = _vtuple(version)
    if have is None:
        return True
    for part in (s.strip() for s in spec.split(",")):
        m = _RANGE.match(part)
        if not m:
            return True
        want = tuple(int(x) for x in m.group(2).split("."))
        n = max(len(have), len(want))
        h, w = have + (0,) * (n - len(have)), want + (0,) * (n - len(want))
        if not {">=": h >= w, "<=": h <= w, "==": h == w, ">": h > w, "<": h < w}[m.group(1)]:
            return False
    return True


def _affects(entry: dict, version: str) -> bool:
    return version in entry.get("versions", []) or any(_in_range(version, r) for r in entry.get("ranges", []))


def advisory_hits(advisories: list[dict], rel: dict, sbom: dict | None) -> list[str]:
    have = {
        ("dev-platform", rel["platform"]["release_version"]),
        (rel["application"]["name"], rel["application"]["version"]),
    }
    have |= {(c.get("name"), c.get("version")) for c in (sbom or {}).get("components", [])}
    hits = []
    for adv in advisories:
        for a in adv.get("affected", []):
            for name, ver in sorted(have, key=str):
                if name == a.get("component") and isinstance(ver, str) and _affects(a, ver):
                    hits.append(f"{adv.get('id')}: {name}@{ver}")
    return sorted(set(hits))


# ---------------------------------------------------------------- authorization


def assess(path: Path, release_sha: str, app_name: str, policy: dict, V, gh, now: datetime) -> dict:
    """Judge one record. {'status': 'authentic'|'ignored', 'problems': [...], ...}. Never raises."""
    verdict: dict = {"file": Path(path).name, "id": None, "status": "ignored", "problems": []}
    try:
        raw = Path(path).read_bytes()
        doc = json.loads(raw)
        assert isinstance(doc, dict)
    except (OSError, ValueError, AssertionError):
        verdict["problems"].append("not a readable JSON object")
        return verdict
    verdict["id"] = doc.get("id")
    try:
        if doc.get("schema") != AUTH_SCHEMA:
            raise ValueError(f"schema must be {AUTH_SCHEMA}")
        for k in ("id", "subject", "decision", "decided_by", "decided_at", "scope"):
            if k not in doc:
                raise ValueError(f"missing {k}")
        if not isinstance(doc["id"], str) or not doc["id"]:
            raise ValueError("id must be a non-empty string")
        sub = doc["subject"] if isinstance(doc["subject"], dict) else {}
        if sub.get("kind") != "application-release":
            raise ValueError("subject.kind must be application-release")
        if sub.get("digest") != release_sha:
            raise ValueError("subject.digest is not this exact release record's digest")
        if doc["decision"] not in ("approved", "rejected", "revoked"):
            raise ValueError("decision must be approved|rejected|revoked")
        by = doc["decided_by"] if isinstance(doc["decided_by"], dict) else {}
        ia = by.get("identity_assertion") if isinstance(by.get("identity_assertion"), dict) else {}
        provider = ia.get("provider")
        auth_policy = policy["authorization"]
        if provider not in V.PROVIDERS or provider not in auth_policy.get("providers", []):
            raise ValueError(f"identity provider {provider!r} is not supported (fail closed)")
        login, evidence = V.PROVIDERS[provider](doc, raw, auth_policy, gh)
        verdict["authenticated_as"] = {"provider": provider, "login": login}
        verdict["evidence"] = evidence
        who = [
            a
            for a in auth_policy.get("approvers", [])
            if a.get("provider") == provider and V._login_eq(a.get("login"), login)
        ]
        if not who:
            raise ValueError(f"{login} is authenticated but is not an approver in the application policy")
        approver = who[0]
        if "application-release" not in approver.get("may_approve", []):
            raise ValueError(f"approver {approver.get('id')} may not approve application releases")
        if app_name not in approver.get("applications", []):
            raise ValueError(f"approver {approver.get('id')} is not authorized for application {app_name!r}")
        verdict["approver"] = approver.get("id")
        scope = doc["scope"] if isinstance(doc["scope"], dict) else {}
        confers = scope.get("confers")
        if not (isinstance(confers, list) and confers) or not set(confers) <= CONFERABLE_CLAIMS:
            raise ValueError(f"scope.confers must be a non-empty subset of {sorted(CONFERABLE_CLAIMS)}")
        if not set(confers) <= set(approver.get("may_confer", [])):
            raise ValueError("scope.confers exceeds the approver's authority in the application policy")
        verdict["scope"] = {"confers": sorted(set(confers)), "not_conferred": NOT_CONFERRED}
        decided = V._ts(doc["decided_at"])
        if decided > now + V.CLOCK_SKEW:
            raise ValueError("decided_at is in the future")
        v = doc.get("validity") or {}
        if v.get("not_before") and V._ts(v["not_before"]) > now:
            raise ValueError("not yet valid")
        if v.get("not_after") and V._ts(v["not_after"]) <= now:
            raise ValueError("expired")
        verdict.update(status="authentic", decision=doc["decision"], decided_at=decided.isoformat())
        verdict["supersedes"] = list(doc.get("supersedes") or [])
    except ValueError as e:
        verdict["problems"].append(str(e))
    except Exception as e:  # any surprise is a refusal, never an approval
        verdict["problems"].append(f"unexpected {type(e).__name__}: {e}")
    return verdict


DEFAULT_MAX_AGE = 300  # seconds an operational verification stays current unless the policy says otherwise
MAX_AGE_CAP = 3600
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class Observed:
    """Wraps the `gh` runner and remembers every call that failed.

    A revocation that could not be authenticated because GitHub could not be reached looks exactly like a record
    that is not authentic. For current-state decisions the two must differ, so a failed call anywhere is recorded
    and makes the current authorization state incomplete (fail closed).
    """

    def __init__(self, gh) -> None:
        self.gh = gh
        self.failures: list[str] = []

    def __call__(self, argv):
        out = self.gh(argv)
        if out[0] != 0 and argv[:2] == [
            "gh",
            "api",
        ]:  # attestation refusals are the platform verdict, not an outage
            self.failures.append(f"{argv[2] if len(argv) > 2 else argv}: {(out[2] or '').strip()[:100]}")
        return out


def _not_found(e: Exception) -> bool:
    return "404" in str(e) or "not found" in str(e).lower()


def snapshot(V, gh, auth_policy: dict, into: Path) -> dict:
    """One consistent view of the authorization evidence: every record at ONE commit of the evidence ref.

    Resolves the ref to a commit id first and reads only at that id, so the listing and every record are the same
    state of the repository. Also audits the history of `authorizations/`: a record that was committed and later
    deleted (for example a revocation) is not silently absent, it makes the state unverifiable. Raises ValueError
    for anything that cannot be established; the caller turns that into a failed check.
    """
    import base64

    repo, ref = auth_policy["evidence_repo"], auth_policy["evidence_ref"]
    try:
        head = V._api(gh, f"repos/{repo}/commits/{ref}")
        sha = head.get("sha") if isinstance(head, dict) else None
        if not (isinstance(sha, str) and _COMMIT.match(sha)):
            raise ValueError("the evidence ref does not resolve to a commit")
        committed = ((head.get("commit") or {}).get("committer") or {}).get("date")
        ever: set[str] = set()
        commits: list[dict] = []
        for page in range(1, 6):
            chunk = V._api(gh, f"repos/{repo}/commits?sha={sha}&path=authorizations&per_page=100&page={page}")
            if not isinstance(chunk, list):
                raise ValueError("history of authorizations is not a list")
            commits += chunk
            if len(chunk) < 100:
                break
        else:
            raise ValueError("history of authorizations is too long to audit")
        for c in commits:
            detail = V._api(gh, f"repos/{repo}/commits/{c['sha']}")
            for f in detail.get("files") or []:
                name = str(f.get("filename"))
                if not name.startswith("authorizations/"):
                    continue
                if f.get("status") == "removed":
                    ever.add(
                        name
                    )  # present before, so it must be absent now only by deletion: compared below
                elif f.get("status") == "renamed" and f.get("previous_filename"):
                    ever.add(str(f["previous_filename"]))
                    ever.add(name)
                else:
                    ever.add(name)
        try:
            listing = V._api(gh, f"repos/{repo}/contents/authorizations?ref={sha}")
        except (RuntimeError, ValueError) as e:
            if not (_not_found(e) and not commits):
                raise ValueError(f"cannot list authorizations: {e}") from None
            listing = []  # no directory and no history: there is genuinely nothing to find
            if isinstance(gh, Observed):
                gh.failures.pop()  # that refusal was the answer, not an outage
        if not isinstance(listing, list):
            raise ValueError("authorizations is not a directory")
        present: set[str] = set()
        out = []
        for item in listing:
            name, path = str(item.get("name")), str(item.get("path"))
            if item.get("type") != "file" or not name.endswith(".json") or not V.AUTH_PATH_RE.match(path):
                continue
            try:
                blob = V._api(gh, f"repos/{repo}/contents/{path}?ref={sha}")
                data = base64.b64decode(blob["content"])
            except (RuntimeError, ValueError, KeyError) as e:
                raise ValueError(f"cannot read {path}: {e}") from None
            f = into / name
            f.write_bytes(data)
            out.append(f)
            present.add(path)
    except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as e:
        raise ValueError(str(e)) from None
    removed = sorted(p for p in ever - present if V.AUTH_PATH_RE.match(p))
    return {
        "repo": repo,
        "ref": ref,
        "head_commit": sha,
        "head_committed_at": committed,
        "records": sorted(Path(x).name for x in out),
        "files": out,
        "history_commits": len(commits),
        "removed": removed,
    }


def current_authorizations(
    V, gh: Observed, auth_policy: dict, into: Path, label: str
) -> tuple[dict, dict, list[str]]:
    """(snapshot, policy pinned to the snapshot commit, problems)."""
    try:
        snap = snapshot(V, gh, auth_policy, into)
    except ValueError as e:
        return {}, auth_policy, [f"{label}: {e}"]
    problems = []
    if snap["removed"]:
        problems.append(
            f"{label}: authorization records were deleted from the evidence history: {snap['removed']}"
        )
    return snap, {**auth_policy, "evidence_ref": snap["head_commit"]}, problems


def still_current(V, gh, auth_policy: dict, head_commit: str) -> bool:
    """True when the evidence ref still points at the commit that was read (nothing was published meanwhile)."""
    try:
        head = V._api(gh, f"repos/{auth_policy['evidence_repo']}/commits/{auth_policy['evidence_ref']}")
        return isinstance(head, dict) and head.get("sha") == head_commit
    except (RuntimeError, ValueError):
        return False


def effective(verdicts: list[dict]) -> dict | None:
    """The one live, authenticated, authorized approval, or None. Latest live decision wins; ties fail closed."""
    live = [v for v in verdicts if v["status"] == "authentic"]
    superseded = {s for v in live for s in v["supersedes"]}
    live = sorted((v for v in live if v["id"] not in superseded), key=lambda v: v["decided_at"])
    if not live:
        return None
    if len(live) > 1 and live[-1]["decided_at"] == live[-2]["decided_at"]:
        live[-1]["problems"].append("ambiguous: two live decisions share a timestamp (fail closed)")
        return None
    return live[-1] if live[-1]["decision"] == "approved" else None


# ---------------------------------------------------------------- evidence bundle

BUNDLE_SCHEMA = "dev-platform.app-release-evidence/v1"
_BUNDLE_PATH = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
BUNDLE_KINDS = ("release", "result", "authorization", "advisory", "sbom")


def load_bundle(directory: Path, pin: str) -> tuple[list[str], dict]:
    """Check an evidence bundle against the operator's pin of its manifest. (problems, files by kind).

    The manifest's own sha256 is the pin: it fixes every listed file's digest, so one operator-held digest
    makes the whole bundle immutable. Unlisted files, missing files, changed bytes, unsafe paths and a release
    entry that is not exactly one are all refusals.
    """
    root = Path(directory)
    files: dict[str, list[Path]] = {k: [] for k in BUNDLE_KINDS}
    problems: list[str] = []
    mpath = root / "manifest.json"
    try:
        raw = mpath.read_bytes()
        manifest = json.loads(raw)
    except (OSError, ValueError) as e:
        return [f"manifest unreadable: {e}"], files
    if hashlib.sha256(raw).hexdigest() != pin:
        return [f"manifest sha256 {hashlib.sha256(raw).hexdigest()} does not match the pin {pin}"], files
    if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
        return [f"manifest schema must be {BUNDLE_SCHEMA}"], files
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["manifest has no entries"], files
    listed: set[str] = {"manifest.json"}
    for e in entries:
        path = e.get("path") if isinstance(e, dict) else None
        if not (isinstance(path, str) and _BUNDLE_PATH.match(path) and ".." not in path.split("/")):
            problems.append(f"unsafe or missing path {path!r}")
            continue
        if e.get("kind") not in BUNDLE_KINDS or not _SHA.match(str(e.get("sha256"))):
            problems.append(f"{path}: bad kind or digest")
            continue
        f = root / path
        if path in listed:
            problems.append(f"{path}: listed twice")
        elif f.is_symlink() or not f.is_file():
            problems.append(f"{path}: missing (or not a regular file)")
        elif sha256_file(f) != e["sha256"]:
            problems.append(f"{path}: bytes differ from the manifest")
        else:
            files[e["kind"]].append(f)
        listed.add(path)
    present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    problems += [f"{x}: present but not listed in the manifest" for x in sorted(present - listed)]
    if len(files["release"]) != 1:
        problems.append("exactly one release entry is required")
    elif manifest.get("release_sha256") != canonical_digest(json.loads(files["release"][0].read_text())):
        problems.append("manifest release_sha256 is not the digest of its release entry")
    return problems, files


def platform_verification(V, entry: dict, archive_sha: str, a, plat_policy: dict, gh, now=None):
    """Re-run the platform verifier for a policy that requires an accepted Dev Platform release.

    Acceptance is itself a current decision: unless inspecting history, the platform authorization records are read
    from the platform policy's evidence repository at one commit and judged with the supplied ones, so an
    acceptance that was revoked (or never was) is not reported accepted from stale evidence. Returns
    (platform verification record, extra checks for the application record, platform currency or None).
    """
    import tempfile

    historical = bool(getattr(a, "historical", False))
    gh = Observed(gh)
    auths = list(a.platform_authorization)
    extra: list[tuple[str, bool, str]] = []
    currency = None
    scratch = tempfile.TemporaryDirectory(prefix="current-platform-auth-")
    try:
        if not historical:
            snap, pinned, problems = current_authorizations(
                V,
                gh,
                plat_policy.get("authorization") or {},
                Path(scratch.name),
                "platform authorization state",
            )
            auths += list(snap.get("files", []))
            plat_policy = {**plat_policy, "authorization": pinned}
            currency = {k: v for k, v in snap.items() if k != "files"}
        doc = V.verify(
            a.platform_archive,
            {"version": entry["version"], "source_revision": entry["source_revision"],
             "archive_sha256": archive_sha, "ref": f"refs/tags/v{entry['version']}", "tree_digest": entry["tree_digest"]},
            plat_policy,
            gh=gh,
            authorizations=auths,
            bundle=a.platform_bundle,
            sbom_bundle=a.platform_sbom_bundle,
            environment=a.platform_environment,
            continuity=a.platform_continuity,
            **({"now": now} if now else {}),
        )  # fmt: skip
        if not historical:
            if gh.failures:
                problems = [*problems, f"{len(gh.failures)} GitHub call(s) failed, e.g. {gh.failures[0]}"]
            extra.append(("platform-authorization-currency", not problems, "; ".join(problems)))
    finally:
        scratch.cleanup()
    return doc, extra, currency


# ---------------------------------------------------------------- verification


def verify(
    release_path: Path,
    policy: dict,
    V,
    *,
    mode: str = "release",
    source_revision: str | None = None,
    locks: list[Path] = (),
    lock_root: Path | None = None,
    artifacts: dict[str, Path] | None = None,
    results: list[Path] = (),
    advisories: list[Path] = (),
    platform_sbom: Path | None = None,
    authorizations: list[Path] = (),
    platform_acceptance: dict | None = None,
    purpose: str = "operational",
    gh=None,
    extra_checks: list[tuple[str, bool, str]] = (),
    now: datetime | None = None,
) -> dict:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    now = now or datetime.now(UTC)
    gh = Observed(gh or V.default_gh)
    rec = Record()
    for cid, ok, detail in extra_checks:
        rec.add(cid, ok, detail)
    coverage = {"verified": [], "not_evaluated": []}
    full = mode == "release"
    try:
        rel = json.loads(Path(release_path).read_text())
    except (OSError, ValueError) as e:
        rel = None
        rec.add("release-record", False, f"unreadable: {e}")
    problems = release_shape_problems(rel) if rel is not None else []
    if rel is not None:
        rec.add("release-record", not problems, "; ".join(problems))
    subject = {"release_sha256": None, "application": None, "version": None}
    if rel is None or problems:
        return _finish(rec, subject, coverage, [], None, mode)
    release_sha = canonical_digest(rel)
    subject = {
        "release_sha256": release_sha,
        "application": rel["application"]["name"],
        "version": rel["application"]["version"],
    }
    ppro = policy_problems(policy)
    rec.add("application-policy", not ppro, "; ".join(ppro))
    if ppro:
        return _finish(rec, subject, coverage, [], None, mode)

    # source
    if full:
        ok = source_revision is not None and source_revision == rel["source"]["revision"]
        rec.add("source-revision", ok, f"release {rel['source']['revision']}, pinned {source_revision}")
        coverage["verified" if ok else "not_evaluated"].append("source")
    else:
        coverage["not_evaluated"].append("source (operator pin of the revision)")

    # dependency state
    if full:
        if locks:
            try:
                got = resolution_digest(list(locks), lock_root or Path("."))
            except (OSError, ValueError) as e:
                got = f"error: {e}"
            rec.add(
                "dependency-resolution", got == rel["dependencies"]["resolution_digest"], f"computed {got}"
            )
            coverage["verified"].append("dependencies")
        else:
            rec.add("dependency-resolution", False, "no lock files supplied (--lock)")
    else:
        coverage["not_evaluated"].append("dependencies (lock file bytes)")

    # artifacts
    supplied = artifacts or {}
    if full:
        want = {a["name"]: a["sha256"] for a in rel["artifacts"]}
        bad = []
        for name, sha in want.items():
            if name not in supplied:
                bad.append(f"{name}: not supplied")
            elif sha256_file(supplied[name]) != sha:
                bad.append(f"{name}: digest differs")
        bad += [f"{n}: supplied but not in the release" for n in supplied if n not in want]
        rec.add("artifact-digests", not bad, "; ".join(bad))
        coverage["verified"].append("artifacts")
    else:
        coverage["not_evaluated"].append("artifacts (bytes)")

    # verification evidence
    by_digest = {}
    for p in results:
        try:
            doc = json.loads(Path(p).read_text())
        except (OSError, ValueError):
            continue
        by_digest[canonical_digest(doc)] = doc
    bad = []
    for ev in rel["evidence"]:
        if ev["kind"] != "result":
            bad.append(f"evidence kind {ev['kind']!r} cannot be verified")
            continue
        res = by_digest.get(ev["sha256"])
        if res is None:
            bad.append(f"{ev['sha256'][:12]}: not supplied (or differs from its digest)")
            continue
        bad += [f"{ev['sha256'][:12]}: {x}" for x in result_problems(res, rel)]
    rec.add("verification-evidence", not bad, "; ".join(bad))
    coverage["verified"].append("evidence")

    # Dev Platform release: allowed by the APPLICATION's policy
    pl = rel["platform"]
    allowed = [
        e
        for e in policy["platform_releases"]
        if e["version"] == pl["release_version"] and e["tree_digest"] == pl["release_tree_digest"]
    ]
    rec.add(
        "platform-release",
        bool(allowed),
        f"{pl['release_version']} tree {pl['release_tree_digest'][:12]} is not in policy.platform_releases",
    )
    coverage["verified"].append("platform release (against the application's policy)")

    # Where the APPLICATION requires it, the platform release must also be owner-ACCEPTED. That is a separate
    # decision about a separate subject, established by the platform verifier re-run (see main); here it is only
    # an additional eligibility condition. It never supplies, and never substitutes for, the application approval.
    entry = allowed[0] if allowed else {}
    if entry.get("require_acceptance") is True:
        pa = platform_acceptance or {}
        sub, acc = pa.get("subject") or {}, pa.get("acceptance") or {}
        problems = []
        if not pa:
            problems.append(
                "the policy requires an accepted Dev Platform release but no platform verification was run"
            )
        else:
            if sub.get("archive_sha256") != entry["archive_sha256"]:
                problems.append("verified platform archive is not the one the policy names")
            if (
                sub.get("tree_digest") != pl["release_tree_digest"]
                or sub.get("version") != pl["release_version"]
            ):
                problems.append("verified platform archive is not the release this record was built with")
            if acc.get("state") != "accepted":
                problems.append(f"platform release state is {acc.get('state')!r}, not 'accepted'")
            elif "platform-baseline" not in acc.get("confers", []):
                problems.append("platform acceptance does not confer platform-baseline")
        rec.add("platform-acceptance", not problems, "; ".join(problems))
        coverage["verified"].append("platform acceptance (platform verifier re-run under operator pins)")

    # advisories
    advs, sbom = [], None
    adv_bad = []
    for p in advisories:
        try:
            a = json.loads(Path(p).read_text())
            assert isinstance(a, dict) and a.get("schema") == ADVISORY
            advs.append(a)
        except (OSError, ValueError, AssertionError):
            adv_bad.append(f"{Path(p).name}: not a readable {ADVISORY}")
    if platform_sbom:
        try:
            sbom = json.loads(Path(platform_sbom).read_text())
            want_sha = (allowed[0] if allowed else {}).get("sbom_sha256")
            if want_sha and sha256_file(platform_sbom) != want_sha:
                adv_bad.append("platform SBOM differs from the policy's sbom_sha256")
        except (OSError, ValueError):
            adv_bad.append("platform SBOM unreadable")
    hits = advisory_hits(advs, rel, sbom) if not adv_bad else []
    rec.add("advisories", not adv_bad and not hits, "; ".join(adv_bad + hits))
    coverage["verified" if advisories else "not_evaluated"].append(
        "advisories" if advisories else "advisories (none supplied: absence is not safety)"
    )

    now = now.astimezone(UTC)
    authorizations = list(authorizations)
    currency: dict = {"purpose": purpose, "status": "historical", "observed_at": now.isoformat()}
    verdicts: list[dict] = []
    if purpose == "operational":
        # Freshness: a current decision needs the CURRENT authorization state. Every record in the evidence
        # repository (a revocation nobody handed us included) is read at one commit and judged exactly like a
        # supplied one; anything that cannot be established makes the decision fail, never approve.
        import tempfile

        auth_policy = policy["authorization"]
        max_age = int((policy.get("freshness") or {}).get("max_age_seconds", DEFAULT_MAX_AGE))
        problems: list[str] = []
        snap: dict = {}
        for _attempt in range(3):
            gh.failures.clear()
            with tempfile.TemporaryDirectory(prefix="current-auth-") as td:
                snap, pinned_auth, problems = current_authorizations(
                    V, gh, auth_policy, Path(td), "authorization state"
                )
                if not snap:
                    verdicts = []
                    break
                have = {sha256_file(Path(x)) for x in authorizations if Path(x).is_file()}
                judged = list(authorizations) + [f for f in snap["files"] if sha256_file(f) not in have]
                pinned_policy = {**policy, "authorization": pinned_auth}
                verdicts = [
                    assess(p, release_sha, rel["application"]["name"], pinned_policy, V, gh, now)
                    for p in judged
                ]
            if still_current(V, gh, auth_policy, snap["head_commit"]):
                break
            problems = ["the evidence ref moved while it was being read (fail closed; re-run)"]
        if gh.failures:
            problems.append(f"{len(gh.failures)} GitHub call(s) failed, e.g. {gh.failures[0]}")
        rec.add("authorization-currency", not problems, "; ".join(problems))
        ok = not problems
        public = {k: v for k, v in snap.items() if k != "files"}
        currency = {
            "purpose": purpose,
            "status": "current" if ok else "unverifiable",
            "observed_at": now.isoformat(),
            "max_age_seconds": max_age,
            "valid_until": (now + timedelta(seconds=max_age)).isoformat() if ok else None,
            "evidence": public,
        }
        if ok:
            coverage["verified"].append(
                f"current authorization state: {len(snap['records'])} record(s) at {snap['head_commit'][:12]}"
            )
    else:
        # Historical inspection: only the supplied records, nothing discovered. It can show that an approval
        # was once authentic; it cannot show that it still is, so it never yields `approved`.
        verdicts = [
            assess(p, release_sha, rel["application"]["name"], policy, V, gh, now) for p in authorizations
        ]
        coverage["not_evaluated"].append(
            "current authorization state (historical inspection: later revocations are not looked for)"
        )
    # assess() binds every record to this exact release digest, so only decisions about it can count.
    auth = effective(verdicts)
    out = _finish(rec, subject, coverage, verdicts, auth, mode, purpose)
    out["currency"] = currency
    if platform_acceptance:
        a = platform_acceptance.get("acceptance") or {}
        out["platform_acceptance"] = {
            "archive_sha256": (platform_acceptance.get("subject") or {}).get("archive_sha256"),
            "state": a.get("state"),
            "authorization": a.get("authorization"),
            "confers": a.get("confers", []),
        }
    return out


def _finish(rec, subject, coverage, verdicts, auth, mode, purpose="operational") -> dict:
    if not rec.all_passed:
        state = "failed"
        reasons = [c["id"] for c in rec.checks if c["status"] == "failed"]
    elif auth is None:
        state = "unapproved"
        reasons = ["no authenticated, authorized, in-force approval bound to this exact release record"]
    elif purpose != "operational":
        state = "historical-approval"
        reasons = [
            f"approval {auth['id']} by {auth['approver']} was authentic against the supplied records; "
            "it is NOT a current authorization (revocations were not looked for)"
        ]
    else:
        state = "approved"
        reasons = [f"authenticated approval {auth['id']} by {auth['approver']}"]
    return {
        "schema": RECORD_SCHEMA,
        "mode": mode,
        "subject": subject,
        "checks": rec.checks,
        "coverage": coverage,
        "approval": {
            "state": state,
            "reasons": reasons,
            "authorization": auth["id"] if auth else None,
            "approver": auth["approver"] if auth else None,
            "decided_at": auth["decided_at"] if auth else None,
            "confers": auth["scope"]["confers"] if auth else [],
            "not_conferred": NOT_CONFERRED,
            "authorization_evidence": verdicts,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "release", type=Path, nargs="?", help="dev-platform.app-release/v1 record (or use --bundle)"
    )
    ap.add_argument("--bundle", type=Path, help="evidence bundle directory (manifest.json + files)")
    ap.add_argument("--manifest-sha256", help="operator pin of the bundle's manifest.json")
    ap.add_argument(
        "--policy", type=Path, required=True, help="application policy (dev-platform.app-trust/v1)"
    )
    ap.add_argument(
        "--platform-verifier", type=Path, required=True, help="tools/verify_release.py (provider registry)"
    )
    ap.add_argument("--platform-verifier-sha256", required=True, help="operator pin of that file")
    ap.add_argument("--mode", choices=("release", "select"), default="release")
    ap.add_argument("--source-revision", help="operator-pinned full commit id of the source")
    ap.add_argument("--lock", type=Path, action="append", default=[])
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--artifact", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--result", type=Path, action="append", default=[])
    ap.add_argument("--advisory", type=Path, action="append", default=[])
    ap.add_argument("--platform-sbom", type=Path)
    ap.add_argument("--authorization", type=Path, action="append", default=[])
    ap.add_argument(
        "--historical",
        action="store_true",
        help="inspection only: judge just the supplied records, look for nothing newer. Never yields `approved` "
        "(a possible approval is reported as `historical-approval`, exit 4). The default is a current decision.",
    )
    ap.add_argument("--platform-archive", type=Path, help="Dev Platform archive the policy requires accepted")
    ap.add_argument(
        "--platform-policy", type=Path, help="platform trust policy (a trust anchor, operator-pinned)"
    )
    ap.add_argument("--platform-policy-sha256", help="operator pin of --platform-policy")
    ap.add_argument("--platform-authorization", type=Path, action="append", default=[])
    ap.add_argument("--platform-bundle", type=Path)
    ap.add_argument("--platform-sbom-bundle", type=Path)
    ap.add_argument("--platform-environment", type=Path)
    ap.add_argument("--platform-continuity", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        policy = json.loads(a.policy.read_text())
    except (OSError, ValueError) as e:
        print(f"policy unreadable: {e}", file=sys.stderr)
        return 2
    V = load_platform_verifier(a.platform_verifier, a.platform_verifier_sha256)
    extra: list[tuple[str, bool, str]] = []
    if a.bundle:
        if not a.manifest_sha256:
            print("--bundle requires --manifest-sha256 (an operator pin)", file=sys.stderr)
            return 2
        problems, files = load_bundle(a.bundle, a.manifest_sha256)
        extra.append(("evidence-bundle", not problems, "; ".join(problems)))
        if problems:
            files = {k: [] for k in BUNDLE_KINDS}  # nothing from a bundle that failed its pin is used
        a.release = a.release or (files["release"][0] if files["release"] else a.bundle / "manifest.json")
        a.result += files["result"]
        a.authorization += files["authorization"]
        a.advisory += files["advisory"]
        a.platform_sbom = a.platform_sbom or (files["sbom"][0] if files["sbom"] else None)
    if a.release is None:
        print("a release record or a valid --bundle is required", file=sys.stderr)
        return 2
    platform_doc = None
    plat_currency = None
    if a.platform_archive:
        if not (a.platform_policy and a.platform_policy_sha256):
            print(
                "--platform-archive requires --platform-policy and --platform-policy-sha256", file=sys.stderr
            )
            return 2
        if sha256_file(a.platform_policy) != a.platform_policy_sha256:
            print("platform policy does not match its operator pin", file=sys.stderr)
            return 2
        want = sha256_file(a.platform_archive)
        entry = next(
            (e for e in policy.get("platform_releases", []) if e.get("require_acceptance") and e.get("archive_sha256") == want),
            None,
        )  # fmt: skip
        if entry:
            platform_doc, more, plat_currency = platform_verification(
                V, entry, want, a, json.loads(a.platform_policy.read_text()), V.default_gh
            )
            extra += more
    arts = {}
    for item in a.artifact:
        name, sep, path = item.partition("=")
        if not sep:
            print(f"--artifact wants NAME=PATH, got {item!r}", file=sys.stderr)
            return 2
        arts[name] = Path(path)
    doc = verify(
        a.release,
        policy,
        V,
        mode=a.mode,
        source_revision=a.source_revision,
        locks=a.lock,
        lock_root=a.root,
        artifacts=arts,
        results=a.result,
        advisories=a.advisory,
        platform_sbom=a.platform_sbom,
        authorizations=a.authorization,
        platform_acceptance=platform_doc,
        purpose="historical" if a.historical else "operational",
        extra_checks=extra,
    )
    if plat_currency is not None:
        doc["currency"]["platform_authorization_state"] = plat_currency
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(text)
    for c in doc["checks"]:
        print(
            f"{c['status'].upper():7} {c['id']}" + (f"  ({c['detail']})" if c["status"] == "failed" else "")
        )
    for v in doc["approval"]["authorization_evidence"]:
        print(
            f"AUTH    {v['file']}: {v['status']}"
            + (f"  ({'; '.join(v['problems'])})" if v["problems"] else "")
        )
    print(f"approval: {doc['approval']['state']}  {'; '.join(doc['approval']['reasons'])}")
    return {"approved": 0, "failed": 1, "unapproved": 3, "historical-approval": 4}[doc["approval"]["state"]]


if __name__ == "__main__":
    sys.exit(main())
