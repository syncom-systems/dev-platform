"""`dev-platform infra` commands for an organization's configuration repository (ADR 0023).

init writes reviewable files only when invoked (never over an existing file without --force); validate and
profile only read; release build writes a new immutable release into the configuration repository. None of
them commits, pushes, contacts GitHub, registers a runner, binds a credential or changes a setting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dev_platform import infra_authz, infra_config, infra_release
from dev_platform.errors import EXIT_OK, EXIT_UNSATISFIED, ConfigError

CONFIG = Path("config/infra.v1.json")
POLICY = Path("authorization/current.v1.json")


def add_parsers(isub) -> None:
    ii = isub.add_parser(
        "init", help="write a starting dev-platform.infra-config/v1 (files only; nothing is activated)"
    )
    ii.add_argument("--root", type=Path, default=Path("."), help="configuration repository (default: .)")
    ii.add_argument("--template", choices=["github-hosted", "self-hosted"], default="github-hosted")
    ii.add_argument("--owner", required=True, help="GitHub organization or user the configuration serves")
    ii.add_argument("--repo", action="append", default=[], help="repository name (repeatable)")
    ii.add_argument("--force", action="store_true", help="replace an existing configuration file")
    iv = isub.add_parser(
        "validate",
        help="validate a configuration, profile, authorization policy or configuration repository "
        "(read-only)",
    )
    iv.add_argument(
        "path", type=Path, nargs="?", default=Path("."), help="a file or a configuration repository"
    )
    iv.add_argument("--workflows", type=Path, help="also check these workflows (with --repo)")
    iv.add_argument("--repo", help="repository whose projected profile the workflows are checked against")
    ip = isub.add_parser(
        "profile", help="preview the dev-platform.infra/v1 profile projected for a repository"
    )
    ip.add_argument("--config", type=Path, default=CONFIG)
    ip.add_argument("--repo", required=True)


def add_operator_parsers(isub) -> None:
    st = isub.add_parser("store", help="the local store of exactly selected configuration releases")
    sts = st.add_subparsers(dest="iscmd", required=True)

    def with_store(q):
        q.add_argument(
            "--store", type=Path, help="default: <data root>/infra (DEV_PLATFORM_HOME, $RUNNER_TEMP in CI)"
        )
        return q

    def with_selection(q, positional=True):
        if positional:
            q.add_argument("version", nargs="?", help="the exact configuration release (YYYY.MM.N)")
        q.add_argument("--digest", help="sha256:<hex>, the exact release-tree digest (the consumer's pin)")
        q.add_argument("--project", type=Path, help="take the selection from this project's [infra] pin")
        return q

    def with_source(q):
        q.add_argument(
            "--source", required=True, help="OWNER/NAME of the configuration repository (no default)"
        )
        q.add_argument("--ref", default="main", help="branch, tag or commit to read (default: main)")
        return q

    with_source(
        with_selection(
            with_store(
                sts.add_parser(
                    "fetch",
                    help="copy exactly one selected release and the current policy from GitHub "
                    "(your identity, gh)",
                )
            )
        )
    )
    with_source(
        with_store(sts.add_parser("sync", help="refresh the current authorization policy (forward only)"))
    )
    im = with_selection(
        with_store(sts.add_parser("import", help="copy one selected release from a local directory"))
    )
    im.add_argument("--from", dest="source_dir", type=Path, required=True, help="a configuration repository")
    im.add_argument(
        "--with-policy", action="store_true", help="also take the directory's authorization policy"
    )
    with_store(sts.add_parser("list", help="stored releases, verified, and the stored policy"))
    dr = isub.add_parser("doctor", help="identities only: CLI, store, policy and the project's selection")
    with_selection(with_store(dr), positional=False)
    dr.add_argument(
        "--root", type=Path, help="resolve from this configuration repository instead of the store"
    )
    dr.add_argument("--repo", help="OWNER/NAME of the consumer (default: the project's origin remote)")
    dr.add_argument("--json", action="store_true")
    ds = isub.add_parser(
        "discover", help="read-only snapshot of runner groups and repository settings (gh GET)"
    )
    ds.add_argument("--owner", required=True)
    ds.add_argument("--repo", action="append", default=[], help="repository name (repeatable)")
    au = isub.add_parser("audit", help="generic findings over a snapshot (offline)")
    au.add_argument("snapshot", type=Path)
    df = isub.add_parser("drift", help="desired configuration versus a snapshot (offline)")
    df.add_argument("snapshot", type=Path)
    df.add_argument("--config", type=Path, default=CONFIG)


def add_release_build(irls) -> None:
    irb = irls.add_parser("build", help="freeze the configuration into a new immutable release")
    irb.add_argument("version", help="YYYY.MM.N, newer than every existing release")
    irb.add_argument("--root", type=Path, default=Path("."), help="configuration repository (default: .)")
    irb.add_argument("--config", type=Path, help=f"default: <root>/{CONFIG}")


def _load(path: Path) -> object:
    try:
        return json.loads(Path(path).read_text())
    except OSError as e:
        raise ConfigError([f"{path}: {e.strerror or e}"]) from None
    except ValueError as e:
        raise ConfigError([f"{path}: not JSON: {e}"]) from None


def _valid_config(path: Path) -> dict:
    cfg = _load(path)
    if errs := infra_config.problems(cfg):
        raise ConfigError([f"{path}: {e}" for e in errs])
    return cfg  # type: ignore[return-value]


def _print(doc: dict) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True))


def cmd_init(args) -> int:
    cfg = infra_config.template(args.template, args.owner, args.repo)
    if errs := infra_config.problems(cfg):  # a template that does not validate is a bug, never written
        raise ConfigError(errs)
    target = args.root / CONFIG
    if (target.exists() or target.is_symlink()) and not args.force:
        raise ConfigError([f"{target} exists (use --force to replace it)"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(infra_release.canonical(cfg))
    _print(
        {
            "written": [str(target)],
            "next": [
                f"review and edit {target}",
                f"dev-platform infra validate {args.root}",
                f"dev-platform infra profile --config {target} --repo <name>   (preview)",
                "commit it through your own review; releases: dev-platform infra release build YYYY.MM.N",
            ],
            "activated": [],
            "notes": infra_config.notes(cfg),
        }
    )
    return EXIT_OK


def _validate_repo(root: Path) -> dict:
    out: dict = {"root": str(root), "problems": [], "notes": []}
    if (root / CONFIG).is_file():
        cfg = _load(root / CONFIG)
        out["config"] = {"path": str(root / CONFIG), "problems": infra_config.problems(cfg)}
        out["problems"] += [f"config: {p}" for p in out["config"]["problems"]]
        if not out["config"]["problems"]:
            out["notes"] += infra_config.notes(cfg)
    if (root / infra_release.INDEX).is_file():
        errs = infra_release.verify(root)
        out["releases"] = {"problems": errs}
        out["problems"] += [f"releases: {p}" for p in errs]
    if (root / POLICY).is_file():
        errs = infra_authz.problems(_load(root / POLICY))
        out["authorization"] = {"path": str(root / POLICY), "problems": errs}
        out["problems"] += [f"authorization: {p}" for p in errs]
    if not any(k in out for k in ("config", "releases", "authorization")):
        out["problems"].append(f"{root}: no {CONFIG}, {infra_release.INDEX} or {POLICY}")
    return out


def _runner_groups(facts: list[dict], cfg: dict) -> list[str]:
    """Jobs that name a runner group the configuration does not declare: an unknown group fails closed."""
    known = {g["name"] for g in cfg.get("runner_groups", [])}
    bad = []
    for f in facts:
        for job in f.get("jobs", []):
            group = job.get("runs_on_group")
            if group is not None and group not in known:
                bad.append(f"{f['file']}: job {job['name']}: runner group {group!r} is not declared")
    return bad


def cmd_validate(args) -> int:
    from dev_platform import prcheck, runners

    path = args.path
    if path.is_dir():
        out = _validate_repo(path)
    else:
        doc = _load(path)
        kind = doc.get("schema") if isinstance(doc, dict) else None
        if kind == infra_config.SCHEMA:
            errs = infra_config.problems(doc)
            out = {"config": str(path), "problems": errs, "notes": [] if errs else infra_config.notes(doc)}
        elif kind == runners.INFRA_SCHEMA:
            out = {"profile": str(path), "problems": runners.validate_profile(doc), "notes": []}
        elif isinstance(doc, dict) and "policy_id" in doc:
            errs = infra_authz.problems(doc)
            out = {"authorization": str(path), "problems": errs, "notes": []}
            if not errs:
                out["identity"] = infra_authz.identity(doc)
        else:
            out = {"path": str(path), "problems": ["not a configuration, profile or authorization policy"]}
    if args.workflows:
        if not args.repo:
            raise ConfigError(["--workflows needs --repo (whose projected profile to check against)"])
        cfg_path = path / CONFIG if path.is_dir() else path
        cfg = _valid_config(cfg_path)
        if args.repo not in {r["name"] for r in cfg["repositories"]}:
            raise ConfigError([f"{cfg_path}: no repository {args.repo!r}"])
        files = {str(p): p.read_text() for p in sorted(args.workflows.glob("*.y*ml"))}
        verdict = prcheck.check(files, infra_config.profile_for(cfg, args.repo), facts=True)
        groups = _runner_groups(verdict.get("facts", []), cfg)
        out["workflows"] = {
            "admission": verdict["admission"],
            "policy_violations": verdict["policy_violations"],
            "incomplete": verdict["incomplete"],
            "unknown_runner_groups": groups,
        }
        if verdict["admission"] != "ok":
            out["problems"].append(f"workflows: admission {verdict['admission']}")
        out["problems"] += [f"workflows: {g}" for g in groups]
    out["valid"] = not out["problems"]
    _print(out)
    return EXIT_OK if out["valid"] else EXIT_UNSATISFIED


def cmd_profile(args) -> int:
    cfg = _valid_config(args.config)
    if args.repo not in {r["name"] for r in cfg["repositories"]}:
        raise ConfigError([f"{args.config}: no repository {args.repo!r}"])
    _print(infra_config.profile_for(cfg, args.repo))
    return EXIT_OK


def cmd_release_build(args) -> int:
    cfg = _valid_config(args.config or args.root / CONFIG)
    digest = infra_release.build(args.root, args.version, infra_config.release_files(cfg, args.version))
    _print(
        {
            "release": args.version,
            "digest": infra_release.wire(digest),
            "path": str(args.root / "releases" / args.version),
            "next": "commit releases/ through your own review; consumers pin version and digest themselves",
        }
    )
    return EXIT_OK


def _selection(args) -> tuple[str, str] | None:
    from dev_platform import infra_store
    from dev_platform.config import parse_pin

    if args.project is not None:
        if getattr(args, "version", None) or args.digest:
            raise ConfigError(["--project or VERSION --digest, not both"])
        import tomllib

        f = args.project / "dev-platform.toml"
        try:
            table = tomllib.loads(f.read_text()).get("infra")
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError([f"{f}: {e}"]) from None
        if not table:
            raise ConfigError([f"{f} has no [infra] pin: the project runs on hosted runners only"])
        errs: list[str] = []
        pin = parse_pin(table, errs)
        if pin is None:
            raise ConfigError([f"{f}: {e}" for e in errs])
        if pin.config_digest_kind == "profile-file":
            raise ConfigError(
                [f"{f}: the pin is a profile-file digest; a store holds configuration releases"]
            )
        return infra_store.selection(pin.config_release, pin.config_digest)
    version = getattr(args, "version", None)
    if version is None and args.digest is None:
        return None
    if not (version and args.digest):
        raise ConfigError(
            ["the exact selection is required: VERSION --digest sha256:<hex> (no default release)"]
        )
    return infra_store.selection(version, args.digest)


def cmd_store(args) -> int:
    from dev_platform import infra_store

    store, chosen = infra_store.location(store=args.store)
    if args.iscmd == "list":
        rows = infra_store.verify(store)
        pol = infra_store.stored_policy(store)
        _print(
            {
                "store": str(store),
                "chosen_by": chosen,
                "releases": rows,
                "authorization_policy": infra_authz.identity(pol) if pol else None,
            }
        )
        return EXIT_UNSATISFIED if any(r["status"] != "ok" for r in rows) else EXIT_OK
    if args.iscmd == "sync":
        src = infra_store.policy_from_github(args.source, args.ref)
        _print(
            {
                "store": str(store),
                "authorization_policy": infra_store.install_policy(store, src),
                "from": src.origin,
            }
        )
        return EXIT_OK
    sel = _selection(args)
    if sel is None:
        raise ConfigError(["the exact selection is required: VERSION --digest sha256:<hex> or --project DIR"])
    version, hexd = sel
    if args.iscmd == "fetch":
        src = infra_store.from_github(args.source, args.ref, version)
    else:
        src = infra_store.from_directory(args.source_dir, version)
    out = {
        "store": str(store),
        "release": version,
        "digest": "sha256:" + hexd,
        "action": infra_store.install_release(store, src, version, "sha256:" + hexd),
        "from": src.origin,
    }
    if args.iscmd == "fetch" or args.with_policy:
        out["authorization_policy"] = infra_store.install_policy(store, src)
    _print(out)
    return EXIT_OK


def _origin_repo(project: Path) -> str | None:
    import re
    import subprocess

    try:
        p = subprocess.run(
            ["git", "-C", str(project), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(
        r"github\.com[:/]([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+?)(?:\.git)?/?$", p.stdout.strip()
    )
    return f"{m.group(1)}/{m.group(2)}" if p.returncode == 0 and m else None


def cmd_doctor(args) -> int:
    """Identities, versions, digests and decision codes only: never a profile, label, endpoint or
    reference."""
    from dev_platform import __version__, infra_provider, infra_store
    from dev_platform.infra import RESOLVE_REQUEST

    if args.root:
        root, kind, chosen = args.root.absolute(), "repository", "--root"
    else:
        root, chosen = infra_store.location(store=args.store)
        kind = "store"
    rep: dict = {
        "schema": "dev-platform.infra-doctor/v1",
        "cli": {"version": __version__},
        "supported_formats": dict(infra_release.FORMATS),
        "configuration": {"kind": kind, "path": str(root), "chosen_by": chosen},
        "releases": [],
        "authorization_policy": None,
        "selection": None,
        "problems": [],
    }
    worst = EXIT_OK

    def problem(text: str, code: int = EXIT_UNSATISFIED) -> None:
        nonlocal worst
        rep["problems"].append(text)
        worst = max(worst, code)

    try:
        rep["releases"] = infra_store.verify(root)  # each indexed release against its digest
    except infra_release.ReleaseError as e:
        problem(f"{e.code}: {e.detail}", 3)
    for r in rep["releases"]:
        if r["status"] != "ok":
            problem(f"release {r['version']}: {r['status']}", 3)
    try:
        pol = infra_store.stored_policy(root)
    except infra_release.ReleaseError as e:
        pol = None
        problem(f"{e.code}: {e.detail}", 3)
    if pol is not None:
        rep["authorization_policy"] = {**infra_authz.identity(pol), "source": infra_store.policy_source(root)}
    else:
        problem("no current authorization policy: nothing resolves (fetch or sync one)")
    try:
        sel = _selection(args)
    except ConfigError as e:
        sel = None
        problem("selection: " + "; ".join(e.problems), 2)
    if sel is not None:
        version, hexd = sel
        repo = args.repo or (_origin_repo(args.project) if args.project else None)
        rep["selection"] = {"repo": repo, "config_release": version, "config_digest": "sha256:" + hexd}
        if repo is None:
            problem("selection: the repository is unknown (pass --repo OWNER/NAME)", 2)
        else:
            req = {
                "schema_version": RESOLVE_REQUEST,
                "repo": repo,
                "event_trust": "trusted",
                "contract": "dev-platform.infra/v1",
                "requested": {"version": version, "digest": "sha256:" + hexd},
                "profile_out": "/dev/null",
            }
            ev = infra_provider.resolve(root, req)["evidence"]  # the profile is discarded
            rep["selection"].update(
                {
                    "decision": ev["decision"],
                    "reasons": [r["code"] for r in ev["reasons"]],
                    "effective_profile_digest": ev["effective_profile_digest"],
                    "narrowed_by_policy": len(ev["narrowed_by_policy"]),
                }
            )
            if ev["decision"] != "resolved":
                code = ev["reasons"][0]["code"] if ev["reasons"] else "denied"
                problem(
                    f"selection {version}: denied: {code}",
                    3 if code == "release-tampered" else EXIT_UNSATISFIED,
                )
    rep["ok"] = worst == EXIT_OK
    if args.json:
        _print(rep)
    else:
        print(f"dev-platform {__version__}; formats: {', '.join(rep['supported_formats'])}")
        print(f"configuration: {kind} {root} ({chosen})")
        for r in rep["releases"]:
            print(f"release {r['version']} {r['digest']} {r['status']}")
        p = rep["authorization_policy"]
        print(
            f"authorization policy {p['id']} revision {p['revision']} {p['digest']}"
            if p
            else "authorization policy: none"
        )
        if s := rep["selection"]:
            print(
                f"selection {s['repo']}: {s['config_release']} {s['config_digest']} -> {s.get('decision')} "
                f"{s.get('reasons') or ''}"
            )
        for x in rep["problems"]:
            print(f"problem: {x}")
        print("ok" if rep["ok"] else "not ready")
    return worst


def cmd_discover(args) -> int:
    from dev_platform import infra_observe

    try:
        snap = infra_observe.discover(args.owner, args.repo)
    except ValueError as e:
        raise ConfigError([str(e)]) from None
    _print(snap)
    return EXIT_OK


def cmd_audit(args) -> int:
    from dev_platform import infra_observe

    findings = infra_observe.audit(_load(args.snapshot))
    _print({"findings": findings})
    return EXIT_UNSATISFIED if any(f["severity"] in ("critical", "high") for f in findings) else EXIT_OK


def cmd_drift(args) -> int:
    from dev_platform import infra_observe

    cfg = _valid_config(args.config)
    rows = infra_observe.drift(cfg, _load(args.snapshot))
    _print({"differences": rows, "note": "reported only: reconciliation is a separate, authorized change"})
    return EXIT_UNSATISFIED if rows else EXIT_OK


COMMANDS = {
    "init": cmd_init,
    "validate": cmd_validate,
    "profile": cmd_profile,
    "store": cmd_store,
    "doctor": cmd_doctor,
    "discover": cmd_discover,
    "audit": cmd_audit,
    "drift": cmd_drift,
}


def run(args) -> int | None:
    """The handler for an `infra` subcommand defined here, or None."""
    if args.icmd == "release" and getattr(args, "ircmd", None) == "build":
        return cmd_release_build(args)
    fn = COMMANDS.get(args.icmd)
    return fn(args) if fn else None


def workflow(args) -> int:
    from dev_platform import workflow_preview

    text, notes = workflow_preview.render(args.project, args.runs_on, args.branch, args.allow_unaccepted)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)
    if args.output:
        try:
            workflow_preview.write_new(args.output, text)
        except FileExistsError:
            raise ConfigError([f"{args.output} exists; the preview never replaces a file"]) from None
        print(
            f"wrote {args.output}: not committed, not enabled; review it and commit it yourself",
            file=sys.stderr,
        )
    else:
        print(text, end="")
    return EXIT_OK
