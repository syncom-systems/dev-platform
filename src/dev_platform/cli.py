"""Command line interface: init, detect, doctor, check, explain, digest."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dev_platform import __version__, engine
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
    ip.add_argument("--force", action="store_true")
    sub.add_parser("detect", parents=[c], help="report discovered facts")
    sub.add_parser("doctor", parents=[c], help="diagnose configuration, pin and environment")
    ex = sub.add_parser("explain", parents=[c], help="show which checks are owed and why")
    _plan_args(ex)
    ck = sub.add_parser("check", parents=[c], help="run owed checks and record evidence")
    _plan_args(ck)
    ck.add_argument("--dry-run", action="store_true")
    ck.add_argument("--result", type=Path, help="write the result record here")
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


def _resolve_and_maybe_exec(cfg, args):
    res = resolve(cfg, protected=protected_context(os.environ, getattr(args, "protected", False)))
    if needs_reexec(res):
        env = reexec_env(res)
        os.execve(sys.executable, [sys.executable, "-m", "dev_platform", *args._argv], env)  # noqa: S606 - launcher re-exec into the verified pin
    return res


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
    res = _resolve_and_maybe_exec(cfg, args)
    previous = json.loads(args.previous.read_text()) if args.previous else None
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
    )
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
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv)
    args._argv = list(argv)
    try:
        return _COMMANDS[args.cmd](args)
    except ConfigError as e:
        for p in e.problems:
            print(f"config error: {p}", file=sys.stderr)
        return e.exit_code
    except DevPlatformError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
