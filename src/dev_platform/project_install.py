"""`dev-platform install` and `dev-platform update`: the only project file is the pin file.

`install` creates dev-platform.toml on first installation (the exact platform release, and optionally the
exact infrastructure configuration release, from their published identities) and then runs `setup` for what
the file pins. When the file exists it is never changed: installing again verifies and reuses what is
installed (idempotent). `update` only proposes a change to that same file (a diff); `--write` applies it,
and the next `install` installs what the file then pins. Both write only dev-platform.toml; every
installed release, toolchain and configuration release lives in the user's data directory (ADR 0027).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from dev_platform import __version__, infra_store, legacy, pinning, projectsetup
from dev_platform.config import CONFIG_FILENAME, load, parse
from dev_platform.errors import EXIT_OK, EXIT_UNSATISFIED, ConfigError
from dev_platform.infra_release import ReleaseError
from dev_platform.locations import Locations


def _find(start: Path, explicit: bool) -> Path | None:
    try:
        return projectsetup.find_project(start, explicit)
    except projectsetup.Refused:
        return None


def _differs(cfg, version, profile, infra_release, infra_digest) -> list[str]:
    out = []
    if version and version != cfg.platform.version:
        out.append(f"release {cfg.platform.version} is pinned, not {version}")
    if profile and profile != cfg.platform.profile:
        out.append(f"profile {cfg.platform.profile} is pinned, not {profile}")
    if infra_release and not (cfg.infra and cfg.infra.config_release == infra_release):
        pinned = cfg.infra.config_release if cfg.infra else "(none)"
        out.append(f"infra release {pinned} is pinned, not {infra_release}")
    if infra_digest and not (cfg.infra and cfg.infra.config_digest == infra_digest):
        pinned = cfg.infra.config_digest if cfg.infra else "(none)"
        out.append(f"infra digest {pinned} is pinned, not {infra_digest}")
    return out


def _executes(pins: dict) -> dict:
    """The release that will execute, apart from the bootstrap CLI that only verifies and launches it."""
    return {
        "bootstrap_cli": {"version": __version__, "role": "verifies and launches the pinned release only"},
        "executes_release": {
            "version": pins["version"],
            "tree_digest": pins["tree_digest_pin"],
            "source_revision": pins["source_revision"],
        },
    }


def _text_identity(rec: dict) -> list[str]:
    cli, rel = rec["bootstrap_cli"], rec["executes_release"]
    return [
        f"bootstrap CLI   dev-platform {cli['version']} ({cli['role']})",
        f"executes        release {rel['version']} (tree {rel['tree_digest']}, revision "
        f"{rel['source_revision']})",
    ]


def _infra_state(cfg, store: Path, source: str | None, run, *, explicit: bool = True) -> dict:
    """Put the pinned configuration release (and the current authorization policy) into the infrastructure
    store from `source`, or report whether the store already holds exactly the pinned one. A `source` that
    only comes from the pin (`[infra].source`, not `explicit`) is used when the release is missing; a held
    release is never fetched again by `install` (`infra store sync` refreshes the policy)."""
    pin = cfg.infra
    version, hexd = infra_store.selection(pin.config_release, pin.config_digest)
    rec = {"release": version, "digest": pin.config_digest, "store": str(store)}
    try:
        held = next((r for r in infra_store.store_index(store)["releases"] if r["version"] == version), None)
        held = held is not None and held["digest"] == hexd
        if source and (explicit or not held):
            src = infra_store.from_github(source, "main", version, runner=run)
            rec["action"] = infra_store.install_release(store, src, version, pin.config_digest)
            rec["authorization_policy"] = infra_store.install_policy(store, src)
            rec["from"] = src.origin
        else:
            rec["action"] = "present" if held else "missing"
            if not held:
                rec["problem"] = (
                    "the pinned configuration release is not in the store: pass --infra-source OWNER/NAME "
                    "(or pin [infra].source)"
                )
    except ReleaseError as e:
        rec["action"], rec["problem"] = "refused", str(e)
    return rec


def install(
    project: Path | None,
    loc: Locations,
    *,
    version: str | None = None,
    profile: str | None = None,
    infra_source: str | None = None,
    infra_release: str | None = None,
    infra_provider: str | None = None,
    infra_digest: str | None = None,
    repo: str = pinning.PLATFORM_REPO,
    dry_run: bool = False,
    infra_store_dir: Path,
    gh=None,
    **setup_opts,
) -> tuple[dict, int]:
    import subprocess

    from dev_platform.cli import starter_config

    gh = gh or subprocess.run
    start = (project or Path.cwd()).resolve()
    root = _find(start, project is not None)
    created = root is None
    identity = None
    if created:
        root = start
        if not profile:
            raise ConfigError(
                [f"no {CONFIG_FILENAME}: pass --profile (a toolchain profile of the release) to create it"]
            )
        if not version:
            raise ConfigError(
                [
                    f"no {CONFIG_FILENAME}: pass --version, the exact platform release to pin. A first "
                    f"installation never defaults to this CLI's own version ({__version__}): the CLI only "
                    "verifies and launches the release that runs"
                ]
            )
        pins = pinning.platform_identity(version, repo, gh)
        identity = _executes(pins)
        text, _ = starter_config(root, pinning.platform_block(pins, profile).split("\n"))
        if infra_release:
            if not (infra_source and infra_provider and infra_digest):
                raise ConfigError(
                    [
                        "--infra-release needs --infra-source OWNER/NAME, --infra-provider NAME and "
                        "--infra-digest sha256:<release-tree digest>, supplied independently of the source "
                        "(there is no default and no latest)"
                    ]
                )
            pin = pinning.infra_pin(infra_source, infra_release, infra_provider, infra_digest, run=gh)
            text = pinning.apply(text, infra=pinning.infra_block(pin))
        parse(tomllib.loads(text))
        if dry_run:
            return {
                "created": False,
                "would_create": str(root / CONFIG_FILENAME),
                "text": text,
                "ok": True,
                **identity,
            }, EXIT_OK
        with open(root / CONFIG_FILENAME, "x") as f:  # never replaces a file
            f.write(text)
    else:
        problems = _differs(load(root), version, profile, infra_release, infra_digest)
        if problems:
            raise projectsetup.Refused(
                f"{root / CONFIG_FILENAME} exists and is not changed by install ({'; '.join(problems)}): "
                "`dev-platform update` proposes the change",
                2,
            )
    rec, code = projectsetup.setup(root, loc, dry_run=dry_run, **setup_opts)
    rec["created"] = created
    if "pinned" in rec:
        p = rec["pinned"]
        rec |= _executes(
            {
                "version": p["version"],
                "tree_digest_pin": p["tree_digest"],
                "source_revision": p["source_revision"],
            }
        )
    cfg = load(root)
    if cfg.infra and not dry_run and "problem" not in rec:
        store = infra_store_dir
        rec["infra"] = _infra_state(
            cfg, store, infra_source or cfg.infra.source, gh, explicit=bool(infra_source)
        )
        if rec["infra"].get("problem"):
            rec["ok"], rec["problem"] = False, f"infra: {rec['infra']['problem']}"
            code = code or EXIT_UNSATISFIED
    return rec, code


def propose(
    project: Path | None,
    *,
    to: str | None = None,
    profile: str | None = None,
    infra_source: str | None = None,
    infra_release: str | None = None,
    infra_provider: str | None = None,
    infra_digest: str | None = None,
    repo: str = pinning.PLATFORM_REPO,
    write: bool = False,
    gh=None,
) -> dict:
    import subprocess

    gh = gh or subprocess.run
    root = _find((project or Path.cwd()).resolve(), project is not None)
    if root is None:
        raise ConfigError([f"no {CONFIG_FILENAME}: `dev-platform install --profile P` creates it"])
    path = root / CONFIG_FILENAME
    cfg = load(root)
    if cfg.platform.self_hosted:
        raise ConfigError([f"{path} is self-hosted (the platform repository): not a consumer"])
    if not (to or infra_release or profile):
        raise ConfigError(["nothing to propose: pass --to VERSION, --profile and/or --infra-release RELEASE"])
    before_0_17 = cfg.platform.source_revision is None  # the identity is in no file of the project's toml yet
    if before_0_17 and not to:
        raise ConfigError(
            [
                f"{path} pins release {cfg.platform.version}, which predates repository isolation (0.17.0): "
                "migrate with --to <exact version, 0.17.0 or later>; nothing else in the project changes"
            ]
        )
    if path.is_symlink():
        raise ConfigError([f"{path} is a symbolic link: the pin file must be a regular file of the project"])
    text = path.read_text()
    platform = infra = None
    if to or profile:
        chosen = profile or cfg.platform.profile
        if not chosen:
            raise ConfigError([f"{path} pins no profile: pass --profile"])
        pins = pinning.platform_identity(to or cfg.platform.version, repo, gh)
        platform = pinning.platform_block(pins, chosen)
    if infra_release:
        provider = infra_provider or (cfg.infra.provider if cfg.infra else None)
        source = infra_source or (cfg.infra.source if cfg.infra else None)
        if not (source and provider and infra_digest):
            raise ConfigError(
                [
                    "--infra-release needs --infra-source OWNER/NAME, --infra-digest sha256:<release-tree "
                    "digest> (supplied independently of the source) and, on first use, --infra-provider NAME"
                ]
            )
        infra = pinning.infra_block(pinning.infra_pin(source, infra_release, provider, infra_digest, run=gh))
    new = pinning.apply(text, platform=platform, infra=infra)
    rec = {
        "file": str(path),
        "changed": new != text,
        "diff": pinning.diff(text, new),
        "written": False,
    }
    if platform:
        rec |= _executes(pins)
    if before_0_17:
        rec["migration"] = {
            "from": cfg.platform.version,
            "to": to,
            "writes": [CONFIG_FILENAME],
            "kept": "every other line of dev-platform.toml and every other file of the project",
        }
    if legacy_files := legacy.integration_files(root):
        rec["legacy_integration"] = legacy_files  # reported, never changed or deleted
    if write and new != text:
        path.write_text(new)
        rec["written"] = True
    return rec
