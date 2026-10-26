"""Consumer configuration contract, schema_version 1 (dev-platform.toml).

Holds project policy only. Installation location and runner inventory are
deliberately not configurable here: see docs/adr/0003 and 0005.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dev_platform.errors import ConfigError
from dev_platform.model import Cost, Obligation, Stage

CONFIG_FILENAME = "dev-platform.toml"
SCHEMA_VERSION = 1
ADAPTERS = ("python", "bazel", "cargo", "exec")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_INFRA_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_KINDS = ("release-tree", "profile-file")
_REV_RE = re.compile(r"^[0-9a-f]{40}$")
VERIFIER_PINS = ("verify_release", "trust_policy", "install_release")  # sha256 of the three trusted tools


@dataclass(frozen=True)
class PlatformPin:
    version: str | None
    sha256: str | None
    self_hosted: bool
    profile: str | None = None
    # The release identity the launcher verifies before it installs anything (0.17.0): with these the project
    # needs no file but dev-platform.toml. All three, or none (a release before 0.17.0 does not know them).
    source_revision: str | None = None
    archive_sha256: str | None = None
    verifier_pins: dict[str, str] | None = None


@dataclass(frozen=True)
class InfraPin:
    provider: str
    config_release: str
    config_digest: str  # "sha256:<64 hex>"
    # What the digest identifies (ADR 0023): "release-tree" (a provider's configuration release, resolver
    # only) or "profile-file" (the exact bytes of one profile). None: either, as before 0.10.0.
    config_digest_kind: str | None = None
    # Where the release can be obtained (`OWNER/NAME` of the configuration repository). A convenience for
    # `install` and `update`, never an authority: authenticity is the pinned digest, and the source takes no
    # part in the identity of a result.
    source: str | None = None


@dataclass(frozen=True)
class RunnerSpec:
    name: str
    os: str = "any"
    arch: str = "any"
    isolation: str = "any"
    credentials: tuple[str, ...] = ()
    fallback: str = "hosted"
    capabilities: tuple[str, ...] = ()
    cache: str = "any"


@dataclass(frozen=True)
class HostTool:
    """A host tool the project's checks need that is not part of the toolchain profile (for example tmux)."""

    name: str
    argv: tuple[str, ...]
    pattern: str
    version: str | None = None


@dataclass(frozen=True)
class Check:
    id: str
    adapter: str
    stages: tuple[Stage, ...]
    obligation: Obligation
    cost: Cost
    inputs: tuple[str, ...]
    targets: tuple[str, ...] = ()
    argv: tuple[str, ...] = ()
    runner: str | None = None
    description: str = ""


@dataclass(frozen=True)
class Config:
    platform: PlatformPin
    project_name: str
    bazel_only: bool
    assurance: str
    declared_languages: tuple[str, ...]
    impact_global: tuple[str, ...]
    impact_ignore: tuple[str, ...]
    runners: dict[str, RunnerSpec] = field(default_factory=dict)
    checks: tuple[Check, ...] = ()
    host_tools: tuple[HostTool, ...] = ()
    infra: InfraPin | None = None


def parse_pin(table: dict, errs: list[str]) -> InfraPin | None:
    """Validate the `[infra]` table. Absent table: hosted-only, as before."""
    if not table:
        return None
    for k in table:
        if k not in {"provider", "config_release", "config_digest", "config_digest_kind", "source"}:
            errs.append(f"infra.{k}: unknown key")
    provider, rel, dig = table.get("provider"), table.get("config_release"), table.get("config_digest")
    kind = table.get("config_digest_kind")
    ok = True
    if kind is not None and kind not in DIGEST_KINDS:
        errs.append(f"infra.config_digest_kind: one of {list(DIGEST_KINDS)} (omit it for either)")
        ok = False
    if not (isinstance(provider, str) and re.match(r"^[a-z][a-z0-9_.-]*$", provider)):
        errs.append("infra.provider: required lowercase name")
        ok = False
    if not (isinstance(rel, str) and _VERSION_RE.match(rel)):
        errs.append("infra.config_release: required exact version like 1.2.3 (no ranges, no latest)")
        ok = False
    if not (isinstance(dig, str) and _INFRA_DIGEST_RE.match(dig)):
        errs.append("infra.config_digest: required 'sha256:' + 64 lowercase hex characters")
        ok = False
    source = table.get("source")
    if source is not None and not (isinstance(source, str) and _SOURCE_RE.fullmatch(source)):
        errs.append("infra.source: OWNER/NAME of the configuration repository")
        ok = False
    return InfraPin(str(provider), str(rel), str(dig), kind, source) if ok else None


def _table(d: dict, key: str, allowed: set[str], where: str, errs: list[str]) -> dict:
    t = d.get(key, {})
    if not isinstance(t, dict):
        errs.append(f"{where}: must be a table")
        return {}
    for k in t:
        if k not in allowed:
            errs.append(f"{where}.{k}: unknown key")
    return t


def _strlist(v: Any, where: str, errs: list[str]) -> tuple[str, ...]:
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        errs.append(f"{where}: must be a list of non-empty strings")
        return ()
    return tuple(v)


def _enum(cls, v: Any, where: str, errs: list[str], default=None):
    if v is None:
        return default
    try:
        return cls(v)
    except ValueError:
        errs.append(f"{where}: {v!r} not one of {[m.value for m in cls]}")
        return default


def parse(data: dict) -> Config:
    errs: list[str] = []
    for k in data:
        if k not in {"schema_version", "platform", "project", "impact", "runner", "check", "host", "infra"}:
            errs.append(f"{k}: unknown top-level key")
    if data.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version: must be {SCHEMA_VERSION}, got {data.get('schema_version')!r}")

    p = _table(
        data,
        "platform",
        {"version", "sha256", "self_hosted", "profile", "source_revision", "archive_sha256", "verifier_pins"},
        "platform",
        errs,
    )
    self_hosted = p.get("self_hosted", False)
    version, sha = p.get("version"), p.get("sha256")
    if self_hosted is True:
        if version or sha:
            errs.append("platform: self_hosted excludes version/sha256")
    else:
        if not (isinstance(p.get("profile"), str) and p["profile"]):
            errs.append("platform.profile: required (the toolchain profile of the pinned release)")
        if not (isinstance(version, str) and _VERSION_RE.match(version)):
            errs.append("platform.version: required exact version like 1.2.3 (ranges are not allowed)")
        if not (isinstance(sha, str) and _SHA_RE.match(sha)):
            errs.append("platform.sha256: required, 64 lowercase hex characters")

    rev, archive, vpins = p.get("source_revision"), p.get("archive_sha256"), p.get("verifier_pins")
    identity = (rev, archive, vpins)
    if self_hosted is True:
        if any(x is not None for x in identity):
            errs.append("platform: self_hosted excludes the release identity keys")
    elif any(x is not None for x in identity):
        if not (isinstance(rev, str) and _REV_RE.match(rev)):
            errs.append(
                "platform.source_revision: 40 lowercase hex characters (with archive_sha256, verifier_pins)"
            )
        if not (isinstance(archive, str) and _SHA_RE.match(archive)):
            errs.append(
                "platform.archive_sha256: 64 lowercase hex characters (with source_revision, verifier_pins)"
            )
        if not isinstance(vpins, dict) or set(vpins) != set(VERIFIER_PINS):
            errs.append(f"platform.verifier_pins: a table with exactly {list(VERIFIER_PINS)}")
        elif not all(isinstance(v, str) and _SHA_RE.match(v) for v in vpins.values()):
            errs.append("platform.verifier_pins: 64 lowercase hex characters each")

    infra_pin = parse_pin(data.get("infra", {}) if isinstance(data.get("infra", {}), dict) else {}, errs)
    if not isinstance(data.get("infra", {}), dict):
        errs.append("infra: must be a table")

    pr = _table(data, "project", {"name", "bazel_only", "assurance", "languages"}, "project", errs)
    name = pr.get("name")
    if not (isinstance(name, str) and name):
        errs.append("project.name: required")
    assurance = pr.get("assurance", "standard")
    if assurance not in ("standard", "security-critical"):
        errs.append("project.assurance: must be 'standard' or 'security-critical'")
    bazel_only = pr.get("bazel_only", False)
    if not isinstance(bazel_only, bool):
        errs.append("project.bazel_only: must be a boolean")
        bazel_only = False
    langs = _strlist(pr.get("languages", []), "project.languages", errs)

    im = _table(data, "impact", {"global", "ignore"}, "impact", errs)
    impact_global = _strlist(im.get("global", []), "impact.global", errs)
    impact_ignore = _strlist(im.get("ignore", []), "impact.ignore", errs)

    runners: dict[str, RunnerSpec] = {}
    rt = data.get("runner", {})
    if not isinstance(rt, dict):
        errs.append("runner: must be a table of named runner requirements")
        rt = {}
    for rname, rv in rt.items():
        w = f"runner.{rname}"
        if not isinstance(rv, dict):
            errs.append(f"{w}: must be a table")
            continue
        for k in rv:
            if k not in {"os", "arch", "isolation", "credentials", "fallback", "capabilities", "cache"}:
                errs.append(f"{w}.{k}: unknown key (physical runner names/labels are not allowed here)")
        spec = RunnerSpec(
            name=rname,
            os=rv.get("os", "any"),
            arch=rv.get("arch", "any"),
            isolation=rv.get("isolation", "any"),
            credentials=_strlist(rv.get("credentials", []), f"{w}.credentials", errs),
            fallback=rv.get("fallback", "hosted"),
            capabilities=_strlist(rv.get("capabilities", []), f"{w}.capabilities", errs),
            cache=rv.get("cache", "any"),
        )
        if spec.cache not in ("any", "none", "read-only", "read-write"):
            errs.append(f"{w}.cache: must be any|none|read-only|read-write")
        if spec.os not in ("any", "linux", "macos"):
            errs.append(f"{w}.os: must be any|linux|macos")
        if spec.arch not in ("any", "x86_64", "arm64"):
            errs.append(f"{w}.arch: must be any|x86_64|arm64")
        if spec.isolation not in ("any", "ephemeral"):
            errs.append(f"{w}.isolation: must be any|ephemeral")
        if spec.fallback not in ("hosted", "none"):
            errs.append(f"{w}.fallback: must be hosted|none")
        runners[rname] = spec

    host: list[HostTool] = []
    raw_host = data.get("host", [])
    if not isinstance(raw_host, list):
        errs.append("host: must be an array of [[host]] tables")
        raw_host = []
    host_seen: set[str] = set()
    for i, h in enumerate(raw_host):
        w = f"host[{h.get('name', i) if isinstance(h, dict) else i}]"
        if not isinstance(h, dict):
            errs.append(f"{w}: must be a table")
            continue
        for k in h:
            if k not in {"name", "argv", "pattern", "version"}:
                errs.append(f"{w}.{k}: unknown key")
        name = h.get("name")
        if not (isinstance(name, str) and _ID_RE.match(name)):
            errs.append(f"{w}.name: required, lowercase [a-z0-9_.-], starting with a letter")
            continue
        if name in host_seen:
            errs.append(f"{w}.name: duplicate")
        host_seen.add(name)
        argv = _strlist(h.get("argv", []), f"{w}.argv", errs)
        if not argv:
            errs.append(f'{w}.argv: required (the probe command, for example ["tmux", "-V"])')
        pat = h.get("pattern")
        try:
            ok = isinstance(pat, str) and re.compile(pat).groups >= 1
        except re.error:
            ok = False
        if not ok:
            errs.append(f"{w}.pattern: required regular expression with a capture group for the version")
        ver = h.get("version")
        if ver is not None and not (isinstance(ver, str) and ver):
            errs.append(f"{w}.version: must be a non-empty string")
        host.append(HostTool(name, argv, pat if isinstance(pat, str) else "", ver))

    checks: list[Check] = []
    seen: set[str] = set()
    raw_checks = data.get("check", [])
    if not isinstance(raw_checks, list) or not raw_checks:
        errs.append("check: at least one [[check]] is required")
        raw_checks = []
    allowed = {
        "id",
        "adapter",
        "stages",
        "obligation",
        "cost",
        "inputs",
        "targets",
        "argv",
        "runner",
        "description",
    }
    for i, c in enumerate(raw_checks):
        if not isinstance(c, dict):
            errs.append(f"check[{i}]: must be a table")
            continue
        cid = c.get("id")
        w = f"check[{cid if isinstance(cid, str) else i}]"
        for k in c:
            if k not in allowed:
                errs.append(f"{w}.{k}: unknown key")
        if not (isinstance(cid, str) and _ID_RE.match(cid)):
            errs.append(f"{w}.id: required, lowercase [a-z0-9_.-], starting with a letter")
            continue
        if cid in seen:
            errs.append(f"{w}.id: duplicate (each check has exactly one authoritative definition)")
            continue
        seen.add(cid)
        adapter = c.get("adapter")
        if adapter not in ADAPTERS:
            errs.append(f"{w}.adapter: must be one of {list(ADAPTERS)}")
        stages_raw = _strlist(c.get("stages", []), f"{w}.stages", errs)
        stages = tuple(s for s in (_enum(Stage, x, f"{w}.stages", errs) for x in stages_raw) if s)
        if not stages:
            errs.append(f"{w}.stages: at least one stage is required")
        obligation = _enum(Obligation, c.get("obligation"), f"{w}.obligation", errs, Obligation.CHANGE)
        cost = _enum(Cost, c.get("cost"), f"{w}.cost", errs, Cost.FAST)
        inputs = _strlist(c.get("inputs", []), f"{w}.inputs", errs)
        targets = _strlist(c.get("targets", []), f"{w}.targets", errs)
        argv = _strlist(c.get("argv", []), f"{w}.argv", errs)
        runner = c.get("runner")
        if runner is not None and runner not in runners:
            errs.append(f"{w}.runner: {runner!r} is not defined under [runner.*]")
        # Semantics (docs/verification-model.md)
        if obligation in (Obligation.ALWAYS, Obligation.CHANGE) and Stage.PRE_MERGE not in stages:
            errs.append(
                f"{w}: a {obligation.value} obligation must include stage 'pre-merge' "
                "(a mandatory check may be slow but may not be deferred out of admission)"
            )
        if obligation is Obligation.PERIODIC and Stage.FULL not in stages:
            errs.append(f"{w}: a periodic obligation must include stage 'full'")
        if obligation is Obligation.CHANGE and not inputs:
            errs.append(f"{w}.inputs: a change-triggered check must declare inputs")
        if adapter == "bazel" and not targets:
            errs.append(f"{w}.targets: bazel adapter requires targets")
        if adapter == "exec" and not argv:
            errs.append(f"{w}.argv: exec adapter requires argv")
        if adapter == "cargo" and bazel_only:
            errs.append(f"{w}: project is bazel_only; the cargo adapter is prohibited")
        if adapter == "exec" and bazel_only and argv and Path(argv[0]).name == "cargo":
            errs.append(f"{w}: project is bazel_only; invoking cargo directly is prohibited")
        if cid and isinstance(adapter, str):
            checks.append(
                Check(
                    cid,
                    adapter,
                    stages,
                    obligation or Obligation.CHANGE,
                    cost or Cost.FAST,
                    inputs,
                    targets,
                    argv,
                    runner,
                    c.get("description", ""),
                )
            )

    if errs:
        raise ConfigError(errs)
    return Config(
        platform=PlatformPin(
            version,
            sha,
            self_hosted is True,
            p.get("profile"),
            rev,
            archive,
            dict(vpins) if isinstance(vpins, dict) else None,
        ),
        project_name=name,
        bazel_only=bazel_only,
        assurance=assurance,
        declared_languages=langs,
        impact_global=impact_global,
        impact_ignore=impact_ignore,
        runners=runners,
        checks=tuple(checks),
        host_tools=tuple(host),
        infra=infra_pin,
    )


def load(project: Path) -> Config:
    path = Path(project) / CONFIG_FILENAME
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError([f"{path}: not found (run `dev-platform init`)"]) from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError([f"{path}: invalid TOML: {e}"]) from None
    return parse(data)
