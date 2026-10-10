"""Command line interface: init, detect, doctor, check, explain, digest."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dev_platform import __version__, engine, isolation, pack, provenance, records, release, toolchain
from dev_platform.config import CONFIG_FILENAME, SCHEMA_VERSION, load
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
    p.add_argument("--infra-profile", type=Path, help="dev-platform.infra/v1 runner profile")
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
    sub.add_parser("doctor", parents=[c], help="diagnose configuration, pin and environment")
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
    rs.add_argument("--advisory", type=Path, action="append", default=[])
    rs.add_argument("--store", type=Path, default=None, help="platform release store (for advisories)")
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
    return toolchain.verify_profile(res.release["toolchains"], profile, root)


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
    langs = sorted(facts["languages"])
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
        "languages = [" + ", ".join(f'"{x}"' for x in langs if x in ("python", "rust")) + "]",
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
    elif "python" in langs:
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
    elif "rust" in langs:
        lines += [
            "[[check]]",
            'id = "cargo.test"',
            'adapter = "cargo"',
            'stages = ["pre-merge", "full"]',
            'obligation = "change"',
            'inputs = ["**/*.rs", "**/Cargo.toml", "Cargo.lock"]',
            "",
        ]
    else:
        raise ConfigError(["no supported language detected; write dev-platform.toml by hand"])
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
                code = code or (EXIT_UNSATISFIED if not env_rec["conformant"] else EXIT_OK)
            if res.mode == "override":
                add("warn", "override active: results are not certifiable")
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
        infra_profile=args.infra_profile,
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
    hit = records.releases_affected(adv, rels)
    consumers = sorted(str(c) for c in args.consumers if records.consumer_release(c) in hit)
    out = {"advisory": adv["id"], "affected_releases": hit, "affected_consumers": consumers}
    _emit(
        args, out, f"advisory {adv['id']}: affected releases {hit or 'none'}; consumers {consumers or 'none'}"
    )
    return EXIT_UNSATISFIED if hit else EXIT_OK


def cmd_toolchain(args) -> int:
    manifest = toolchain.validate(json.loads(args.manifest.read_text()))
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


def cmd_rollback(args) -> int:
    results = {records.canonical_digest(r): r for r in _load_json(args.result)}
    plat = {}
    store = args.store or default_store()
    if args.advisory and store.is_dir():
        for d in sorted(store.iterdir()):
            if (d / "release.json").is_file():
                doc = release.load(d)
                doc["sbom_doc"] = json.loads((d / doc["sbom"]["path"]).read_text())
                plat[d.name] = doc
    out = provenance.select_rollback(
        args.application,
        args.current,
        _load_json(args.release),
        results,
        _load_json(args.authorization),
        advisories=_load_json(args.advisory),
        platform_releases=plat,
    )
    print(json.dumps(out, indent=2, sort_keys=True))
    return EXIT_OK if out["eligible"] else EXIT_UNSATISFIED


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
    "release": cmd_release,
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
