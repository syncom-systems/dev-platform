"""Command line interface: init, detect, doctor, check, explain, digest."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dev_platform import (
    __version__,
    appverify,
    bundle,
    depsubmit,
    engine,
    evidence,
    isolation,
    pack,
    provenance,
    records,
    release,
    toolchain,
)
from dev_platform import (
    infra as infra_mod,
)
from dev_platform.config import CONFIG_FILENAME, SCHEMA_VERSION, load, parse_pin
from dev_platform.detect import detect, is_bazel_workspace
from dev_platform.digest import tree_digest
from dev_platform.errors import (
    EXIT_OK,
    EXIT_UNSATISFIED,
    EXIT_USAGE,
    ConfigError,
    DevPlatformError,
)
from dev_platform.model import Stage
from dev_platform.resolve import default_store, needs_reexec, protected_context, reexec_env, resolve


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--project", type=Path, default=Path("."), help="consumer repository root")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def _plan_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--stage", choices=[s.value for s in Stage], default=Stage.PRE_MERGE.value)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--changed", nargs="+", metavar="PATH", help="explicit changed paths")
    g.add_argument("--base", metavar="REF", help="diff against merge-base with REF")
    g.add_argument("--staged", action="store_true", help="use the staged change")
    p.add_argument("--previous", type=Path, help="previous result record to carry evidence from")
    p.add_argument(
        "--infra-profile",
        type=Path,
        help="dev-platform.infra/v1 runner profile (with an [infra] pin: vendored, sha256 equals the pin)",
    )
    p.add_argument(
        "--infra-resolver",
        help="operator-supplied provider command (trusted events only; env DEV_PLATFORM_INFRA_RESOLVER)",
    )
    p.add_argument("--repository", help="owner/name sent to the resolver (default: $GITHUB_REPOSITORY)")
    p.add_argument("--event-trust", choices=["trusted", "untrusted"], default="untrusted")
    p.add_argument("--protected", action="store_true", help="treat as a protected run")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dev-platform", description=__doc__)
    ap.add_argument("--version", action="version", version=f"dev-platform {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = _common()
    ip = sub.add_parser("init", parents=[c], help="write a starter dev-platform.toml")
    ip.add_argument("--platform-version", default=__version__)
    ip.add_argument("--sha256", help="digest of the release tree (default: computed from the store)")
    ip.add_argument("--profile", required=True, help="toolchain profile of the pinned release")
    ip.add_argument("--force", action="store_true")
    sub.add_parser("detect", parents=[c], help="report discovered facts")
    dc = sub.add_parser("doctor", parents=[c], help="diagnose configuration, pin and environment")
    dc.add_argument(
        "--infra-profile", type=Path, help="vendored infra profile to check against the [infra] pin"
    )
    ex = sub.add_parser("explain", parents=[c], help="show which checks are owed and why")
    _plan_args(ex)
    ck = sub.add_parser("check", parents=[c], help="run owed checks and record evidence")
    _plan_args(ck)
    ck.add_argument("--dry-run", action="store_true")
    ck.add_argument("--result", type=Path, help="write the result record here")
    ck.add_argument(
        "--isolate-env",
        action="store_true",
        help="run checks with a scrubbed environment (allowlist, verified-tool PATH, private HOME/TMPDIR)",
    )
    ck.add_argument("--isolate-keep", action="append", default=[], metavar="NAME", help="also pass NAME")
    rl = sub.add_parser("release", help="build or verify an immutable platform release")
    rsub = rl.add_subparsers(dest="rcmd", required=True)
    rb = rsub.add_parser("build", help="create <out>/<version>/ with toolchain manifest and SBOM")
    rb.add_argument("--version", dest="rversion", required=True)
    rb.add_argument("--out", type=Path, required=True)
    rb.add_argument("--toolchains", type=Path, default=Path("toolchains/manifest.json"))
    rb.add_argument("--src", type=Path, default=None)
    rb.add_argument("--source-uri")
    rb.add_argument("--source-revision")
    rp = rsub.add_parser("pack", help="write a deterministic .tar.gz of a release directory")
    rp.add_argument("path", type=Path)
    rp.add_argument("--out", type=Path, required=True)
    ri = rsub.add_parser("install", help="verify an archive and install it write-once into the store")
    ri.add_argument("archive", type=Path)
    ri.add_argument("--archive-sha256", required=True)
    ri.add_argument("--tree-sha256", help="expected pin digest (recommended: your consumer's pin)")
    ri.add_argument("--store", type=Path, default=None)
    rv = rsub.add_parser("verify", help="verify a release directory and print its pin digest")
    rv.add_argument("path", type=Path)
    va = sub.add_parser("validate", help="validate an app-release, authorization or advisory record")
    va.add_argument("file", type=Path, nargs="+")
    af = sub.add_parser("affected", help="which releases and consumers does an advisory affect")
    af.add_argument("--advisory", type=Path, required=True)
    af.add_argument("--store", type=Path, default=None)
    af.add_argument("--json", action="store_true")
    af.add_argument(
        "--impact", action="store_true", help="full impact analysis incl. fixes and patch proposals"
    )
    af.add_argument("--github", metavar="REPO", help="with --impact: analyse the GitHub releases of REPO")
    af.add_argument("--policy", type=Path, default=Path("planning/release-policy.json"))
    af.add_argument(
        "--github-draft", action="store_true", help="with --impact: print a draft repository advisory"
    )
    af.add_argument("consumers", type=Path, nargs="*", help="dev-platform.toml, result or app-release files")
    tc = sub.add_parser("toolchain", help="inspect toolchain closures")
    tsub = tc.add_subparsers(dest="tcmd", required=True)
    tm = tsub.add_parser("measure", help="measure installed tool closures (to author manifest pins)")
    tm.add_argument("--manifest", type=Path, default=Path("toolchains/manifest.json"))
    tm.add_argument("--profile", required=True)
    tv = tsub.add_parser("verify", help="verify the installed environment against a manifest profile")
    tv.add_argument("--manifest", type=Path, default=Path("toolchains/manifest.json"))
    tv.add_argument("--profile", required=True)
    tv.add_argument("--require-certifiable", action="store_true", help="exit 1 unless every tool is strong")
    tp = tsub.add_parser(
        "provision", help="realize a profile's pinned tools into a version-keyed local store"
    )
    tp.add_argument("--manifest", type=Path, default=Path("toolchains/manifest.json"))
    tp.add_argument("--pinned", action="store_true", help="use the manifest of the project's pinned release")
    tp.add_argument("--project", type=Path, default=Path("."))
    tp.add_argument("--profile", required=True)
    tp.add_argument("--dest", type=Path, default=Path(".devenv"))
    tb = tsub.add_parser(
        "prove-bazel-rust",
        help="prove Bazel uses the declared Rust toolchain, not a host rustc (runs bazel, never cargo)",
    )
    tb.add_argument("--project", type=Path, default=Path("."))
    tb.add_argument("--target", default="//...", help="Bazel target pattern whose Rustc actions are examined")
    tb.add_argument("--out", type=Path, help="write the proof record here")
    pv = sub.add_parser("provenance", help="assemble an application-release record from a certified result")
    psub = pv.add_subparsers(dest="pcmd", required=True)
    pa = psub.add_parser("assemble")
    pa.add_argument("--result", type=Path, required=True)
    pa.add_argument("--name", required=True)
    pa.add_argument("--app-version", required=True)
    pa.add_argument("--source-uri", required=True)
    pa.add_argument("--artifact", action="append", default=[], metavar="NAME=SHA256")
    pa.add_argument("--lock", type=Path, action="append", default=[], help="dependency resolution file")
    pa.add_argument("--root", type=Path, default=Path("."))
    pa.add_argument("--out", type=Path)
    rb = sub.add_parser("rollback", help="select a previously approved application release")
    rsub2 = rb.add_subparsers(dest="rbcmd", required=True)
    rs = rsub2.add_parser("select")
    rs.add_argument("--application", required=True)
    rs.add_argument("--current", required=True)
    rs.add_argument("--release", type=Path, action="append", default=[], help="app-release records")
    rs.add_argument("--result", type=Path, action="append", default=[], help="result records (evidence)")
    rs.add_argument("--authorization", type=Path, action="append", default=[])
    rs.add_argument(
        "--audit-state",
        type=Path,
        help="directory keeping already-audited evidence-history facts between candidates and runs",
    )
    rs.add_argument("--advisory", type=Path, action="append", default=[])
    rs.add_argument("--store", type=Path, default=None, help="platform release store (for advisories)")
    rs.add_argument("--evidence-store", type=Path, help="content-addressed evidence store (results)")
    rs.add_argument(
        "--bundle",
        action="append",
        default=[],
        metavar="DIR=MANIFEST_SHA256",
        help="pinned evidence bundle (immutable release, results, approvals, advisories)",
    )
    rs.add_argument(
        "--allow-unbundled",
        action="store_true",
        help="also consider --release records that are not from a pinned bundle",
    )
    rs.add_argument("--app-policy", type=Path, help="application policy (dev-platform.app-trust/v1)")
    rs.add_argument("--verifier", type=Path, help="tools/verify_app_release.py")
    rs.add_argument("--verifier-sha256", help="operator pin of --verifier")
    rs.add_argument("--platform-verifier", type=Path, help="tools/verify_release.py (provider registry)")
    rs.add_argument("--platform-verifier-sha256", help="operator pin of --platform-verifier")
    rs.add_argument("--platform-sbom", type=Path, help="SBOM of the platform release (component advisories)")
    platform_flags = {"archive": "ARCHIVE", "policy": "POLICY", "bundle": "BUNDLE", "sbom-bundle": "BUNDLE",
                      "environment": "RECORD", "continuity": "RECORD"}  # fmt: skip
    for flag, meta in platform_flags.items():
        rs.add_argument(
            f"--platform-{flag}",
            type=Path,
            metavar=meta,
            help="only for policies that require an accepted Dev Platform release",
        )
    rs.add_argument("--platform-policy-sha256", help="operator pin of --platform-policy")
    rs.add_argument("--platform-authorization", type=Path, action="append", default=[])
    rs.add_argument(
        "--unauthenticated",
        action="store_true",
        help="diagnostic only: shape-check approvals without authenticating them (never an approval)",
    )
    ev = sub.add_parser("evidence", help="write-once content-addressed evidence store")
    esub = ev.add_subparsers(dest="ecmd", required=True)
    ep = esub.add_parser("put")
    ep.add_argument("--store", type=Path, required=True)
    ep.add_argument("record", type=Path, nargs="+")
    ev2 = esub.add_parser("verify", help="re-derive every stored digest; exit 1 on any mismatch")
    ev2.add_argument("--store", type=Path, required=True)
    eb = esub.add_parser("bundle", help="write a write-once evidence bundle for one application release")
    eb.add_argument("--out", type=Path, required=True)
    eb.add_argument("--release", type=Path, required=True)
    eb.add_argument("--result", type=Path, action="append", default=[])
    eb.add_argument("--authorization", type=Path, action="append", default=[])
    eb.add_argument("--advisory", type=Path, action="append", default=[])
    eb.add_argument("--sbom", type=Path)
    eb.add_argument("--previous", help="manifest sha256 of the bundle this one follows")
    ebv = esub.add_parser("bundle-verify", help="check a bundle against the pinned manifest digest")
    ebv.add_argument("bundle", type=Path)
    ebv.add_argument("--manifest-sha256", required=True)
    ds = sub.add_parser(
        "dependency-snapshot",
        help="GitHub dependency-submission snapshot of the toolchain manifest's tool components",
    )
    ds.add_argument("--manifest", type=Path, default=Path("toolchains/manifest.json"))
    ds.add_argument("--profile", action="append", default=[], help="limit to these profiles")
    ds.add_argument("--platform-version", required=True)
    ds.add_argument("--sha", required=True, help="commit the snapshot describes")
    ds.add_argument("--ref", required=True, help="e.g. refs/heads/main")
    ds.add_argument("--job-id", required=True)
    ds.add_argument("--scanned", required=True, help="RFC 3339 UTC timestamp")
    ds.add_argument("--out", type=Path)
    pc = sub.add_parser(
        "pr-check",
        help="static workflow check against the infra profile (violations, incomplete, indicators)",
    )
    pc.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    pc.add_argument("--infra-profile", type=Path, default=None, help="dev-platform.infra/v1 incl. admission")
    ic = sub.add_parser("infra", help="provider-side tools for dev-platform.infra/v1 (validate, event trust)")
    isub = ic.add_subparsers(dest="icmd", required=True)
    icc = isub.add_parser(
        "check", help="validate a profile; optionally check workflows and repository visibility"
    )
    icc.add_argument("profile", type=Path)
    icc.add_argument("--workflows", type=Path, help="directory of workflow files to run pr-check on")
    icc.add_argument(
        "--repo-visibility", choices=["public", "private"], help="warn on persistent runners if public"
    )
    idg = isub.add_parser(
        "digest", help="print the sha256: identity of a vendored profile (the consumer's pin)"
    )
    idg.add_argument("profile", type=Path)
    icr = isub.add_parser(
        "check-resolution",
        help="provider CI: judge a resolver result against a consumer pin exactly as the engine does",
    )
    icr.add_argument("--config-release", required=True)
    icr.add_argument("--config-digest", required=True)
    icr.add_argument("--provider", default="provider")
    icr.add_argument("--result", type=Path, required=True)
    icr.add_argument("--profile", type=Path)
    icr.add_argument("--event-trust", choices=["trusted", "untrusted"], default="trusted")
    ie = isub.add_parser("event-trust", help="normative event trust for a CI context")
    ie.add_argument("--event", required=True)
    ie.add_argument("--head-repo")
    ie.add_argument("--base-repo")
    ie.add_argument("--protected-ref", action="store_true")
    ie.add_argument("--same-repo-pr-opt-in", action="store_true")
    ie.add_argument("--triggering-event-trust", choices=["trusted", "untrusted"])
    pl = sub.add_parser("plan", help="release planning: readiness, versions, notes (never grants acceptance)")
    psub = pl.add_subparsers(dest="pcmd", required=True)
    for name, hlp in (
        ("readiness", "is the milestone's scope complete (=> implementation-complete only)"),
        ("notes", "generate descriptive release notes from merged work"),
        ("manifest", "index linking scope, artifact and evidence"),
    ):
        pp = psub.add_parser(name, help=hlp)
        pp.add_argument("--milestone", required=True)
        pp.add_argument("--repo", default="syncom-systems/dev-platform")
        pp.add_argument("--snapshot", type=Path, help="offline snapshot JSON instead of the GitHub API")
        pp.add_argument("--policy", type=Path, default=Path("planning/release-policy.json"))
        pp.add_argument("--version", help="release version (notes, manifest)")
        pp.add_argument("--verification", type=Path, help="verification record (notes, manifest)")
        pp.add_argument("--identity", type=Path, help="release identity.json (manifest)")
        pp.add_argument("--qualification", type=Path, action="append", default=[], help="qualify result JSON")
    pa = psub.add_parser(
        "assign", help="assign PRs to the milestone of the issue they close (dry run unless --apply)"
    )
    pa.add_argument("--repo", default="syncom-systems/dev-platform")
    pa.add_argument("--snapshot", type=Path)
    pa.add_argument("--apply", action="store_true")
    pv = psub.add_parser(
        "version-check", help="does this version follow the versioning policy for these changes"
    )
    pv.add_argument("--previous", required=True)
    pv.add_argument("--new", required=True)
    pv.add_argument("--kind", action="append", default=[], help="declared change kind (repeatable)")
    pv.add_argument("--old-manifest", type=Path)
    pv.add_argument("--new-manifest", type=Path, default=Path("toolchains/manifest.json"))
    pv.add_argument("--old-schemas", type=Path)
    pv.add_argument("--new-schemas", type=Path, default=Path("schemas"))
    pv.add_argument("--criteria-met", action="append", default=[])
    pv.add_argument("--policy", type=Path, default=Path("planning/release-policy.json"))
    pt = psub.add_parser(
        "patches", help="propose security patch releases for an advisory's affected versions"
    )
    pt.add_argument("--affected", action="append", required=True)
    pt.add_argument("--existing", action="append", required=True, help="existing stable versions")
    pt.add_argument("--policy", type=Path, default=Path("planning/release-policy.json"))
    ps = psub.add_parser(
        "state", help="derive the lifecycle state from evidence (accepted only via the pinned verifier)"
    )
    ps.add_argument("--milestone", required=True)
    ps.add_argument("--repo", default="syncom-systems/dev-platform")
    ps.add_argument("--snapshot", type=Path)
    ps.add_argument("--policy", type=Path, default=Path("planning/release-policy.json"))
    ps.add_argument("--archive-sha256", required=True)
    ps.add_argument("--ci-verification", type=Path)
    ps.add_argument("--independent-verification", type=Path)
    ps.add_argument(
        "--immutable", action="store_true", help="the GitHub release is immutable (checked by the caller)"
    )
    ps.add_argument("--notice", type=Path, action="append", default=[], help="superseded/revoked notice JSON")
    ps.add_argument("--verifier", type=Path, help="tools/verify_release.py (run to observe `accepted`)")
    ps.add_argument("--verifier-sha256")
    ps.add_argument(
        "--verifier-arg", action="append", default=[], help="argument for the verifier (repeatable)"
    )
    dg = sub.add_parser("digest", help="print the release tree digest of a directory")
    dg.add_argument("path", type=Path)
    return ap


def _emit(args, doc: dict, text: str) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True) if args.json else text)


def _changed(args, root: Path):
    if args.changed is not None:
        return tuple(sorted(args.changed))
    if args.staged or args.base:
        return engine.git_changed(root, base=args.base, staged=args.staged)
    return None  # unknown: fail closed


class _Delegated(Exception):
    def __init__(self, code: int):
        self.code = code


def _resolve_and_delegate(cfg, args):
    """Resolve the pinned release; if we are not running it, run it (from its private snapshot)."""
    res = resolve(cfg, protected=protected_context(os.environ, getattr(args, "protected", False)))
    if needs_reexec(res):
        try:
            child = subprocess.run([sys.executable, "-m", "dev_platform", *args._argv], env=reexec_env(res))
        finally:
            res.dispose()
        raise _Delegated(child.returncode)
    return res


def environment_for(cfg, res, root: Path) -> dict | None:
    profile = cfg.platform.profile
    if not profile or not res.release:
        return None
    env = toolchain.verify_profile(res.release["toolchains"], profile, root)
    return toolchain.with_host_requirements(env, toolchain.host_requirements(cfg.host_tools))


def exec_env_for(cfg, res) -> dict[str, str]:
    if not cfg.platform.profile or not res.release:
        return {}
    return toolchain.runtime_env(res.release["toolchains"], cfg.platform.profile)


def cmd_detect(args) -> int:
    facts = detect(args.project)
    lines = [f"languages: {facts['languages'] or '(none)'}"] + [
        f"build system {k}: {', '.join(v)}" for k, v in facts["build_systems"].items()
    ]
    _emit(args, facts, "\n".join(lines))
    return EXIT_OK


def cmd_init(args) -> int:
    root = args.project
    target = root / CONFIG_FILENAME
    if target.exists() and not args.force:
        raise ConfigError([f"{target} exists (use --force)"])
    sha = args.sha256
    vrel = default_store() / args.platform_version
    if (vrel / "release.json").is_file():
        profiles = release.load(vrel)["toolchains"]["profiles"]
        if args.profile not in profiles:
            raise ConfigError([f"profile {args.profile!r} not in release (have {sorted(profiles)})"])
    if not sha:
        vdir = default_store() / args.platform_version
        if not vdir.is_dir():
            raise ConfigError(
                [f"no installed release {args.platform_version} in {vdir.parent}; pass --sha256 explicitly"]
            )
        sha = tree_digest(vdir)
    facts = detect(root)
    bazel = is_bazel_workspace(facts)
    # Checks come from build-system markers and real test layout, never from stray files with a language
    # extension (pilot finding: a Rust workspace with an incidental .py file got a python.unittest check).
    cargo = bool(facts["build_systems"].get("cargo")) and not bazel
    py_tests = (root / "tests").is_dir() and any((root / "tests").rglob("test_*.py"))
    python = "python" in facts["languages"] and py_tests and not bazel
    langs = sorted(
        ({"python"} if python or (bazel and "python" in facts["languages"]) else set())
        | ({"rust"} if cargo or (bazel and "rust" in facts["languages"]) else set())
    )
    lines = [
        f"schema_version = {SCHEMA_VERSION}",
        "",
        "[platform]",
        f'version = "{args.platform_version}"',
        f'sha256 = "{sha}"',
        f'profile = "{args.profile}"',
        "",
        "[project]",
        f'name = "{root.resolve().name}"',
        f"bazel_only = {str(bazel).lower()}",
        "# assurance is a declaration; it is never inferred from source files",
        'assurance = "standard"',
        "languages = [" + ", ".join(f'"{x}"' for x in langs) + "]",
        "",
    ]
    if bazel:
        lines += [
            "[[check]]",
            'id = "bazel.test"',
            'adapter = "bazel"',
            'targets = ["//..."]',
            'stages = ["pre-merge", "full"]',
            'obligation = "change"',
            'cost = "slow"',
            'inputs = ["**"]',
            "",
        ]
    if python:
        lines += [
            "[[check]]",
            'id = "python.unittest"',
            'adapter = "python"',
            'targets = ["tests"]',
            'stages = ["pre-commit", "pre-merge", "full"]',
            'obligation = "change"',
            'inputs = ["**/*.py"]',
            "",
        ]
    if cargo:
        lines += [
            "[[check]]",
            'id = "cargo.test"',
            'adapter = "cargo"',
            'stages = ["pre-merge", "full"]',
            'obligation = "change"',
            'inputs = ["**/*.rs", "**/Cargo.toml", "Cargo.lock"]',
            "",
        ]
    if not (bazel or python or cargo):
        raise ConfigError(
            ["no supported build system or test layout detected; write dev-platform.toml by hand"]
        )
    target.write_text("\n".join(lines))
    _emit(args, {"written": str(target), "bazel_only": bazel}, f"wrote {target}")
    return EXIT_OK


def cmd_doctor(args) -> int:
    findings: list[dict] = []

    def add(level: str, msg: str) -> None:
        findings.append({"level": level, "message": msg})

    add("ok" if sys.version_info >= (3, 11) else "error", f"python {sys.version.split()[0]}")
    code = EXIT_OK
    try:
        cfg = load(args.project)
        add("ok", f"{CONFIG_FILENAME} valid ({len(cfg.checks)} checks)")
        try:
            res = resolve(cfg, protected=protected_context(os.environ, args.__dict__.get("protected", False)))
            add("ok", f"platform resolved: mode={res.mode} version={res.version}")
            env_rec = environment_for(cfg, res, args.project.resolve())
            res.dispose()
            if env_rec:
                for t in env_rec["tools"]:
                    add(
                        "ok" if t["status"] == "ok" else "error",
                        f"tool {t['name']}: expected {t['expected']} observed {t['observed']} "
                        f"[{t['identity']}] {t['status']}",
                    )
                for h in env_rec.get("host_requirements", []):
                    add(
                        "ok" if h["status"] == "ok" else "error",
                        f"host tool {h['name']}: expected {h['expected'] or 'any'} observed {h['observed']} "
                        f"[{h['identity']}] {h['status']}",
                    )
                code = code or (EXIT_UNSATISFIED if not env_rec["conformant"] else EXIT_OK)
            if res.mode == "override":
                add("warn", "override active: results are not certifiable")
            if cfg.infra:
                pin = cfg.infra
                add("ok", f"infra pinned: {pin.provider} {pin.config_release} {pin.config_digest}")
                if args.__dict__.get("infra_profile"):
                    r = infra_mod.from_vendored_file(cfg.infra, args.infra_profile)
                    add(
                        "ok" if r.status == infra_mod.RESOLVED else "error",
                        f"infra profile: {r.status} {'; '.join(r.reasons)}",
                    )
        except DevPlatformError as e:
            add("error", str(e))
            code = e.exit_code
        facts = detect(args.project)
        for lang in facts["languages"]:
            if lang in ("python", "rust") and lang not in cfg.declared_languages:
                add(
                    "warn",
                    f"detected {lang} is not declared in project.languages (facts do not create obligations)",
                )
    except ConfigError as e:
        for p in e.problems:
            add("error", p)
        code = EXIT_USAGE
    add("ok", "no private infrastructure required")
    text = "\n".join(f"[{f['level']}] {f['message']}" for f in findings)
    _emit(args, {"findings": findings}, text)
    return code


def _plan(args, execute: bool) -> tuple[dict, int]:
    cfg = load(args.project)
    res = _resolve_and_delegate(cfg, args)
    previous = json.loads(args.previous.read_text()) if args.previous else None
    infra_scratch = Path(tempfile.mkdtemp(prefix="dp-infra-"))
    infra_res = infra_mod.resolve(
        cfg.infra,
        event_trust=args.event_trust,
        repo=args.repository or os.environ.get("GITHUB_REPOSITORY"),
        profile_file=args.infra_profile,
        resolver_argv=shlex.split(args.infra_resolver or os.environ.get("DEV_PLATFORM_INFRA_RESOLVER", ""))
        or None,
        scratch=infra_scratch,
    )
    execution, executor, scratch = None, engine.subprocess_executor, None
    if getattr(args, "isolate_env", False):
        profile = (
            res.release["toolchains"]["profiles"].get(cfg.platform.profile or "", {}) if res.release else {}
        )
        scratch = Path(tempfile.mkdtemp(prefix="dp-exec-"))
        env, execution = isolation.scrub(
            dict(os.environ),
            path_dirs=isolation.tool_dirs(sorted(profile.get("tools", {}))),
            scratch=scratch,
            keep=tuple(args.isolate_keep),
        )
        executor = engine.make_executor(env)
    doc = engine.build(
        cfg,
        args.project.resolve(),
        res,
        Stage(args.stage),
        _changed(args, args.project),
        execute=execute,
        previous=previous,
        infra=infra_res,
        event_trust=args.event_trust,
        revision=engine.git_revision(args.project),
        dirty=engine.git_dirty(args.project),
        environment=environment_for(cfg, res, args.project.resolve()),
        exec_env=exec_env_for(cfg, res),
        executor=executor,
        execution=execution,
    )
    if scratch:
        shutil.rmtree(scratch, ignore_errors=True)
    shutil.rmtree(infra_scratch, ignore_errors=True)
    return doc, doc["exit"]


def render(doc: dict) -> str:
    cs = doc["change_set"]
    out = [
        f"stage {doc['stage']}  platform {doc['platform']['mode']}"
        f" {doc['platform']['pinned_version'] or ''}".rstrip(),
        "changes: "
        + (", ".join(cs["paths"]) if cs["known"] else "UNKNOWN (fail closed: all owed checks selected)"),
    ]
    for c in doc["checks"]:
        mark = {"passed": "PASS", "failed": "FAIL", "unavailable": "UNAVAIL"}.get(
            c["outcome"], "OWED" if c["selected"] else "skip"
        )
        out.append(f"  {mark:7} {c['id']} [{c['obligation']}, {c['cost']}] -> {c['state']}")
        for r in c["reasons"]:
            out.append(f"            why: {r}")
        if "runner" in c:
            r = c["runner"]
            out.append(f"            runner: {r['id'] or 'UNROUTABLE'} ({r['reason']})")
    if doc["unsatisfied_obligations"]:
        out.append("unsatisfied obligations: " + ", ".join(doc["unsatisfied_obligations"]))
    if doc["regressions"]:
        out.append("regressions: " + ", ".join(doc["regressions"]))
    if doc["admission"]:
        out.append(f"admission: {doc['admission']}")
    cert = doc["certification"]
    out.append(
        "certified: " + ("yes" if cert["certified"] else "no (" + "; ".join(cert["blockers"][:3]) + ")")
    )
    return "\n".join(out)


def cmd_explain(args) -> int:
    doc, _ = _plan(args, execute=False)
    _emit(args, doc, render(doc))
    return EXIT_OK


def cmd_check(args) -> int:
    doc, code = _plan(args, execute=not args.dry_run)
    if args.result:
        args.result.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    _emit(args, doc, render(doc))
    return EXIT_UNSATISFIED if code else EXIT_OK


def cmd_release(args) -> int:
    if args.rcmd == "build":
        src = args.src or Path(__file__).resolve().parent.parent
        dest = release.build(
            src,
            args.toolchains,
            args.out,
            args.rversion,
            source_uri=args.source_uri,
            source_revision=args.source_revision,
        )
        print(f"built {dest}\npin sha256 = {tree_digest(dest)}")
        return EXIT_OK
    if args.rcmd == "pack":
        print(f"archive sha256 = {pack.pack(args.path, args.out)}")
        return EXIT_OK
    if args.rcmd == "install":
        dest = pack.install(
            args.archive,
            args.store or default_store(),
            expect_archive_sha256=args.archive_sha256,
            expect_tree_sha256=args.tree_sha256,
        )
        print(f"installed {dest}\npin sha256 = {tree_digest(dest)}")
        return EXIT_OK
    doc = release.load(args.path)
    print(
        f"ok: {doc['platform']['version']} source {doc['platform']['source_digest']}\n"
        f"pin sha256 = {tree_digest(args.path)}"
    )
    return EXIT_OK


def cmd_validate(args) -> int:
    bad = 0
    for f in args.file:
        problems = records.validate_file(f)
        bad += bool(problems)
        print(f"{f}: " + ("ok" if not problems else "INVALID"))
        for p in problems:
            print(f"  {p}")
    return EXIT_USAGE if bad else EXIT_OK


def cmd_affected(args) -> int:
    adv = json.loads(args.advisory.read_text())
    problems = records.validate_advisory(adv)
    if problems:
        raise ConfigError(problems)
    store = args.store or default_store()
    rels = {}
    if store.is_dir():
        for d in sorted(store.iterdir()):
            if (d / "release.json").is_file():
                doc = release.load(d)
                doc["sbom_doc"] = json.loads((d / doc["sbom"]["path"]).read_text())
                rels[d.name] = doc
    if args.impact:
        from . import advisories

        if args.github:
            rels = advisories.github_releases(args.github)
        pins = {str(c): records.consumer_release(c) for c in args.consumers}
        pol = json.loads(args.policy.read_text())
        out = advisories.impact(adv, rels, {k: v for k, v in pins.items() if v}, pol)
        if args.github_draft:
            out = {"impact": out, "github_advisory_draft": advisories.github_advisory_draft(adv, out)}
            print(json.dumps(out, indent=2, sort_keys=True))
            return EXIT_UNSATISFIED if out["impact"]["releases"] else EXIT_OK
        print(json.dumps(out, indent=2, sort_keys=True))
        return EXIT_UNSATISFIED if out["releases"] else EXIT_OK
    hit = records.releases_affected(adv, rels)
    consumers = sorted(str(c) for c in args.consumers if records.consumer_release(c) in hit)
    out = {"advisory": adv["id"], "affected_releases": hit, "affected_consumers": consumers}
    _emit(
        args, out, f"advisory {adv['id']}: affected releases {hit or 'none'}; consumers {consumers or 'none'}"
    )
    return EXIT_UNSATISFIED if hit else EXIT_OK


def cmd_toolchain(args) -> int:
    if args.tcmd == "provision" and args.pinned:
        from . import provision

        cfg = load(args.project)
        res = resolve(cfg, protected=protected_context(os.environ, False))
        try:
            if not res.release:
                raise ConfigError(["no pinned release resolved (override or self-hosted mode has none)"])
            done = provision.provision(res.release["toolchains"], args.profile, args.dest)
        finally:
            res.dispose()
        print(
            json.dumps({"profile": args.profile, "dest": str(args.dest), "installed": done}, sort_keys=True)
        )
        print(f"then: export PATH={args.dest / 'bin'}:$PATH  and run: dev-platform toolchain verify")
        return EXIT_OK
    if args.tcmd == "prove-bazel-rust":
        from . import bazel_rust

        proof = bazel_rust.prove(args.project, target=args.target)
        text = json.dumps(proof, indent=2, sort_keys=True)
        if args.out:
            args.out.write_text(text + "\n")
        print(text)
        return EXIT_OK if proof["ok"] else EXIT_UNSATISFIED
    manifest = toolchain.validate(json.loads(args.manifest.read_text()))
    if args.tcmd == "provision":
        from . import provision

        done = provision.provision(manifest, args.profile, args.dest)
        print(
            json.dumps({"profile": args.profile, "dest": str(args.dest), "installed": done}, sort_keys=True)
        )
        return EXIT_OK
    if args.tcmd == "verify":
        rec = toolchain.verify_profile(manifest, args.profile, Path.cwd())
        print(json.dumps(rec, indent=2, sort_keys=True))
        bad = not rec["conformant"] or (args.require_certifiable and rec["assurance"] != "certifiable")
        return EXIT_UNSATISFIED if bad else EXIT_OK
    print(json.dumps(toolchain.measure(manifest, args.profile), indent=2, sort_keys=True))
    return EXIT_OK


def _load_json(paths):
    return [json.loads(Path(p).read_text()) for p in paths]


def cmd_provenance(args) -> int:
    result = json.loads(args.result.read_text())
    arts = []
    for a in args.artifact:
        name, _, sha = a.partition("=")
        arts.append({"name": name, "sha256": sha})
    if not args.lock:
        raise ConfigError(["at least one --lock (dependency resolution file) is required"])
    doc = provenance.assemble(
        result,
        name=args.name,
        version=args.app_version,
        source_uri=args.source_uri,
        artifacts=arts,
        resolution=provenance.resolution_digest(args.lock, args.root),
    )
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text)
    print(text, end="")
    return EXIT_OK


def cmd_dependency_snapshot(args) -> int:
    doc = depsubmit.snapshot(
        json.loads(args.manifest.read_text()),
        platform_version=args.platform_version,
        sha=args.sha,
        ref=args.ref,
        scanned=args.scanned,
        job_id=args.job_id,
        profiles=args.profile or None,
        manifest_file=str(args.manifest),
    )
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text)
    print(text, end="")
    return EXIT_OK


def cmd_evidence(args) -> int:
    if args.ecmd == "put":
        for f in args.record:
            print(f"{evidence.put(args.store, json.loads(f.read_text()))}  {f}")
        return EXIT_OK
    if args.ecmd == "bundle":
        pin = bundle.build(
            args.out,
            args.release,
            results=args.result,
            authorizations=args.authorization,
            advisories=args.advisory,
            sbom=args.sbom,
            previous=args.previous,
        )
        print(f"{pin}  manifest sha256 of {args.out} (pin this out of band)")
        return EXIT_OK
    if args.ecmd == "bundle-verify":
        problems = bundle.verify(args.bundle, args.manifest_sha256)
        print(json.dumps({"problems": problems}, indent=2))
        return EXIT_OK if not problems else EXIT_UNSATISFIED
    good, bad = evidence.scan(args.store)
    print(json.dumps({"records": len(good), "problems": bad}, indent=2))
    return EXIT_OK if not bad else EXIT_UNSATISFIED


def _bundle_inputs(specs: list[str]) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    """(releases, results, authorizations, advisories) from pinned bundles; a bad bundle aborts selection."""
    rel, res, auth, adv = [], [], [], []
    for spec in specs:
        d, sep, pin = spec.rpartition("=")
        if not sep:
            raise ConfigError([f"--bundle wants DIR=MANIFEST_SHA256, got {spec!r}"])
        problems = bundle.verify(Path(d), pin)
        if problems:
            raise ConfigError([f"bundle {d}: {p}" for p in problems])
        root = Path(d)
        rel.append(root / "release.json")
        res += sorted(root.glob("results/*.json"))
        auth += sorted(root.glob("authorizations/*.json"))
        adv += sorted(root.glob("advisories/*.json"))
    return rel, res, auth, adv


def _platform_args(args) -> list[str]:
    out: list[str] = []
    for flag in ("archive", "policy", "bundle", "sbom_bundle", "environment", "continuity"):
        v = getattr(args, f"platform_{flag}")
        if v:
            out += [f"--platform-{flag.replace('_', '-')}", str(v)]
    if args.platform_policy_sha256:
        out += ["--platform-policy-sha256", args.platform_policy_sha256]
    for a in args.platform_authorization:
        out += ["--platform-authorization", str(a)]
    return out


def cmd_rollback(args) -> int:
    b_rel, b_res, b_auth, b_adv = _bundle_inputs(args.bundle)
    args.authorization = [*args.authorization, *b_auth]
    args.advisory = [*args.advisory, *b_adv]
    args.release = [*args.release, *b_rel]
    results = {records.canonical_digest(r): r for r in _load_json([*args.result, *b_res])}
    immutable = None if args.allow_unbundled else {records.canonical_digest(r) for r in _load_json(b_rel)}
    if args.evidence_store:
        stored, bad = evidence.scan(args.evidence_store)
        if bad:
            raise ConfigError([f"evidence store: {b}" for b in bad])
        results |= {d: r for d, r in stored.items() if r.get("schema") == engine.RESULT_SCHEMA}
    plat = {}
    store = args.store or default_store()
    if args.advisory and store.is_dir():
        for d in sorted(store.iterdir()):
            if (d / "release.json").is_file():
                doc = release.load(d)
                doc["sbom_doc"] = json.loads((d / doc["sbom"]["path"]).read_text())
                plat[d.name] = doc
    authenticate = None
    if not args.unauthenticated:
        need = ("app_policy", "verifier", "verifier_sha256", "platform_verifier", "platform_verifier_sha256")
        missing = [f"--{n.replace('_', '-')}" for n in need if not getattr(args, n)]
        if missing:
            raise ConfigError(
                [
                    f"approvals are authenticated by the pinned independent verifier; missing {missing} "
                    "(or pass --unauthenticated for a diagnostic that is never an approval)"
                ]
            )
        authenticate = appverify.AppVerifier(
            args.verifier,
            args.verifier_sha256,
            args.platform_verifier,
            args.platform_verifier_sha256,
            args.app_policy,
            results=results,
            authorizations=args.authorization,
            advisories=args.advisory,
            platform_sbom=args.platform_sbom,
            platform_args=_platform_args(args),
            audit_state=args.audit_state,
        )
    out = provenance.select_rollback(
        args.application,
        args.current,
        _load_json(args.release),
        results,
        _load_json(args.authorization),
        advisories=_load_json(args.advisory),
        platform_releases=plat,
        authenticate=authenticate,
        immutable=immutable,
    )
    print(json.dumps(out, indent=2, sort_keys=True))
    return EXIT_OK if out["eligible"] else EXIT_UNSATISFIED


def _j(path):
    return json.loads(Path(path).read_text())


def _plan_snapshot(args) -> dict:
    from . import planning

    if args.snapshot:
        return _j(args.snapshot)
    return planning.fetch_snapshot(args.repo, args.milestone)


def cmd_plan(args) -> int:
    from . import lifecycle, planning

    if args.pcmd == "queue":
        snap = _j(args.snapshot) if args.snapshot else planning.fetch_unassigned(args.repo)
        print(json.dumps(planning.work_queue(snap["items"]), indent=2, sort_keys=True))
        return EXIT_OK
    if args.pcmd == "assign":
        snap = _j(args.snapshot) if args.snapshot else planning.fetch_unassigned(args.repo)
        plan = planning.plan_assignments(snap)
        n = planning.apply_assignments(args.repo, plan, snap.get("milestones", [])) if args.apply else 0
        print(json.dumps({"assignments": plan, "applied": n}, indent=2, sort_keys=True))
        return EXIT_OK
    policy = planning.load_policy(args.policy)
    if args.pcmd == "version-check":
        kinds = list(args.kind)
        if args.old_manifest:
            kinds += lifecycle.diff_manifests(_j(args.old_manifest), _j(args.new_manifest))
        if args.old_schemas:
            kinds += lifecycle.diff_schemas(args.old_schemas, args.new_schemas)
        problems = lifecycle.check_version(
            args.previous, args.new, kinds, policy, criteria_met=args.criteria_met
        )
        print(json.dumps({"kinds": sorted(set(kinds)), "problems": problems}, indent=2, sort_keys=True))
        return EXIT_UNSATISFIED if problems else EXIT_OK
    if args.pcmd == "patches":
        out = lifecycle.patch_plan(args.affected, args.existing, policy)
        print(json.dumps({"proposals": out}, indent=2, sort_keys=True))
        return EXIT_OK
    snap = _plan_snapshot(args)
    rd = planning.readiness(snap, policy)
    if args.pcmd == "readiness":
        print(json.dumps(rd, indent=2, sort_keys=True))
        return EXIT_OK if rd["ready"] else EXIT_UNSATISFIED
    verification = _j(args.verification) if getattr(args, "verification", None) else None
    if args.pcmd == "notes":
        print(planning.release_notes(snap, args.version or snap["milestone"]["title"], verification), end="")
        return EXIT_OK
    if args.pcmd == "manifest":
        identity = _j(args.identity) if args.identity else None
        qual = [_j(q) for q in args.qualification]
        lc = lifecycle.derive(
            {
                "planning": {"ready": rd["ready"]},
                "archive_sha256": (identity or {}).get("archive_sha256"),
                "ci_verification": None,
                "independent_verification": verification,
            }
        ).doc()
        doc = planning.release_manifest(
            args.version or snap["milestone"]["title"], snap, rd, lc, identity, verification, qual
        )
        print(json.dumps(doc, indent=2, sort_keys=True))
        return EXIT_OK
    facts = {
        "planning": {"ready": rd["ready"]},
        "archive_sha256": args.archive_sha256,
        "ci_verification": _j(args.ci_verification) if args.ci_verification else None,
        "independent_verification": _j(args.independent_verification)
        if args.independent_verification
        else None,
        "published": {"immutable": args.immutable},
        "notices": [_j(n) for n in args.notice],
    }
    if args.verifier:
        if not args.verifier_sha256:
            raise ConfigError(["--verifier requires --verifier-sha256 (an operator-supplied pin)"])
        facts["verifier"] = lifecycle.run_verifier(args.verifier, args.verifier_sha256, args.verifier_arg)
    d = lifecycle.derive(facts).doc()
    d["readiness"] = {"ready": rd["ready"], "blockers": rd["blockers"]}
    print(json.dumps(d, indent=2, sort_keys=True))
    return EXIT_OK


def cmd_infra(args) -> int:
    from . import prcheck, runners

    if args.icmd == "event-trust":
        t = runners.event_trust(
            args.event,
            head_repo=args.head_repo,
            base_repo=args.base_repo,
            protected_ref=args.protected_ref,
            same_repo_pr_opt_in=args.same_repo_pr_opt_in,
            triggering_event_trust=args.triggering_event_trust,
        )
        print(json.dumps({"event": args.event, "event_trust": t}, sort_keys=True))
        return EXIT_OK
    if args.icmd == "digest":
        print(infra_mod.file_digest(args.profile))
        return EXIT_OK
    if args.icmd == "check-resolution":
        errs: list[str] = []
        pin = parse_pin(
            {
                "provider": args.provider,
                "config_release": args.config_release,
                "config_digest": args.config_digest,
            },
            errs,
        )
        if pin is None:
            raise ConfigError(errs)
        request = infra_mod.request_for(pin, repo=None, event_trust=args.event_trust)
        data = args.profile.read_bytes() if args.profile else None
        r = infra_mod.evaluate(pin, request, _j(args.result), data)
        print(json.dumps(r.evidence(), indent=2, sort_keys=True))
        return EXIT_OK if r.status in (infra_mod.RESOLVED, infra_mod.HOSTED_ONLY) else EXIT_UNSATISFIED
    doc = _j(args.profile)
    problems = runners.validate_profile(doc)
    out: dict = {"profile": str(args.profile), "valid": not problems, "problems": problems, "warnings": []}
    if not problems:
        persistent = [r["id"] for r in doc["runners"] if r["isolation"] == "persistent"]
        if args.repo_visibility == "public" and persistent:
            out["warnings"].append(
                f"public repository but the profile offers persistent runners {persistent}: select another "
                "profile for public repositories (persistent runners must never serve untrusted events)"
            )
        if args.workflows:
            files = {str(p): p.read_text() for p in sorted(args.workflows.glob("*.y*ml"))}
            out["pr_check"] = prcheck.check(files, doc)
    print(json.dumps(out, indent=2, sort_keys=True))
    bad = problems or (out.get("pr_check") or {}).get("admission") not in (None, "ok")
    return EXIT_UNSATISFIED if bad else EXIT_OK


def cmd_pr_check(args) -> int:
    from . import prcheck

    files = {str(p): p.read_text() for p in sorted(args.workflows.glob("*.y*ml"))}
    profile = _j(args.infra_profile) if args.infra_profile else None
    try:
        out = prcheck.check(files, profile)
    except ValueError as e:
        raise ConfigError([str(e)]) from None
    print(json.dumps(out, indent=2, sort_keys=True))
    return EXIT_OK if out["admission"] == "ok" else EXIT_UNSATISFIED


def cmd_digest(args) -> int:
    print(tree_digest(args.path))
    return EXIT_OK


_COMMANDS = {
    "init": cmd_init,
    "detect": cmd_detect,
    "doctor": cmd_doctor,
    "explain": cmd_explain,
    "check": cmd_check,
    "digest": cmd_digest,
    "toolchain": cmd_toolchain,
    "provenance": cmd_provenance,
    "rollback": cmd_rollback,
    "evidence": cmd_evidence,
    "dependency-snapshot": cmd_dependency_snapshot,
    "release": cmd_release,
    "plan": cmd_plan,
    "pr-check": cmd_pr_check,
    "infra": cmd_infra,
    "validate": cmd_validate,
    "affected": cmd_affected,
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv)
    args._argv = list(argv)
    try:
        return _COMMANDS[args.cmd](args)
    except _Delegated as d:
        return d.code
    except ConfigError as e:
        for p in e.problems:
            print(f"config error: {p}", file=sys.stderr)
        return e.exit_code
    except DevPlatformError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
