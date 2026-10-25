"""The project's pins: what `dev-platform install` writes first and `dev-platform update` proposes.

dev-platform.toml is the only platform-managed file in a project (ADR 0027). Its `[platform]` table holds
the whole release identity and its optional `[infra]` table the exact configuration release; this module
renders those two tables from the published identities and replaces exactly them, leaving every other
byte of the file alone.

Identities come from the public platform repository (`releases/<version>/identity.json`, cross-checked
against the commit its tag names) and from the configuration repository's own release index. Nothing is
trusted yet: the trusted installer verifies the platform archive against these pins and attestations, and
the infrastructure store verifies the configuration release against its indexed digest, before either is
used.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import tomllib
from collections.abc import Callable

from dev_platform import infra_store
from dev_platform.config import CONFIG_FILENAME, VERIFIER_PINS, parse
from dev_platform.errors import ConfigError
from dev_platform.infra_release import ReleaseError, digest_of

PLATFORM_REPO = "syncom-systems/dev-platform"
ISOLATION_FROM = (
    0,
    17,
    0,
)  # the first release that understands the identity keys and writes nothing into projects
_VER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.]+)?$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REV = re.compile(r"^[0-9a-f]{40}$")
_TOOL_KEYS = {  # identity.json name of each pinned tool
    "verify_release": "verify_release.py_sha256",
    "trust_policy": "trust_policy_sha256",
    "install_release": "install_release.py_sha256",
}
Run = Callable[..., subprocess.CompletedProcess]


def version_tuple(v: str) -> tuple[int, int, int]:
    m = _VER.match(v or "")
    if not m:
        raise ConfigError([f"version {v!r}: an exact version like 1.2.3 (no ranges, no latest)"])
    return tuple(int(x) for x in m.groups()[:3])


def _gh(args: list[str], run: Run) -> bytes:
    try:
        p = run(["gh", *args], capture_output=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise ConfigError([f"gh is needed to read published identities: {e}"]) from None
    if p.returncode:
        first = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()[:1]
        raise ConfigError([f"GitHub refused or could not be reached: {first[0] if first else p.returncode}"])
    return p.stdout


def platform_identity(version: str, repo: str = PLATFORM_REPO, run: Run = subprocess.run) -> dict:
    """The pins of platform release `version`: its published identity record, which must name the commit
    its tag names. Raises ConfigError for anything else."""
    if version_tuple(version) < ISOLATION_FROM:
        raise ConfigError(
            [
                f"release {version} predates repository isolation (0.17.0): it does not read the identity "
                "from dev-platform.toml and its toolchain preparation writes into the project"
            ]
        )
    raw = _gh(
        ["api", "--method", "GET", f"repos/{repo}/contents/releases/{version}/identity.json",
         "-H", "Accept: application/vnd.github.raw"],
        run,
    )  # fmt: skip
    try:
        ident = json.loads(raw)
        vp = ident["verifier_pins"]
        pins = {
            "version": ident["version"],
            "source_revision": ident["source_revision"],
            "archive_sha256": ident["archive_sha256"],
            "tree_digest_pin": ident["tree_digest_pin"],
            "verifier_pins": {k: vp[v] for k, v in _TOOL_KEYS.items()},
        }
    except (ValueError, KeyError, TypeError) as e:
        raise ConfigError([f"releases/{version}/identity.json: not a release identity ({e})"]) from None
    good = (
        pins["version"] == version
        and _REV.match(str(pins["source_revision"]))
        and all(_SHA.match(str(x)) for x in (pins["archive_sha256"], pins["tree_digest_pin"]))
        and all(_SHA.match(str(x)) for x in pins["verifier_pins"].values())
    )
    if not good:
        raise ConfigError([f"releases/{version}/identity.json: malformed or for another version"])
    tag = _gh(["api", "--method", "GET", f"repos/{repo}/commits/v{version}", "--jq", ".sha"], run)
    if tag.decode().strip() != pins["source_revision"]:
        raise ConfigError(
            [f"tag v{version} does not name the identity's source_revision: refusing to pin it"]
        )
    return pins


def platform_block(pins: dict, profile: str) -> str:
    vp = pins["verifier_pins"]
    return "\n".join(
        [
            "[platform]",
            f'version = "{pins["version"]}"',
            f'sha256 = "{pins["tree_digest_pin"]}"',
            f'profile = "{profile}"',
            f'source_revision = "{pins["source_revision"]}"',
            f'archive_sha256 = "{pins["archive_sha256"]}"',
            "",
            "[platform.verifier_pins]",
            *[f'{k} = "{vp[k]}"' for k in VERIFIER_PINS],
        ]
    )


def infra_pin(source: str, release: str, provider: str, ref: str = "main", run: Run = subprocess.run) -> dict:
    """The exact pin of configuration release `release` from the configuration repository's index, with the
    received release tree checked against the indexed digest."""
    try:
        src = infra_store.from_github(source, ref, release, runner=run)
        entry = next((r for r in src.index()["releases"] if r["version"] == release), None)
        if entry is None:
            raise ReleaseError("version-unknown", f"{source}: no release {release} in the index")
        if digest_of(src.release(release)) != entry["digest"]:
            raise ReleaseError(
                "release-tampered", f"{release}: received content does not have the indexed digest"
            )
    except ReleaseError as e:
        raise ConfigError([f"infra {release}: {e}"]) from None
    return {
        "provider": provider,
        "config_release": release,
        "config_digest": "sha256:" + entry["digest"],
        "config_digest_kind": "release-tree",
        "contract": entry["contract"],
    }


def infra_block(pin: dict) -> str:
    return "\n".join(
        [
            "[infra]",
            f'provider = "{pin["provider"]}"',
            f'config_release = "{pin["config_release"]}"',
            f'config_digest = "{pin["config_digest"]}"',
            f'config_digest_kind = "{pin["config_digest_kind"]}"',
        ]
    )


_HEADER = re.compile(r"^\s*\[{1,2}\s*([A-Za-z0-9_.\"'-]+)\s*\]{1,2}\s*(#.*)?$")


def _region(lines: list[str], table: str) -> tuple[int, int] | None:
    """[start, end) of `table` and its sub-tables: from its header to its last content line (blank lines and
    comments after it belong to what follows)."""
    start = end = None
    for i, line in enumerate(lines):
        m = _HEADER.match(line)
        if m:
            inside = m.group(1) == table or m.group(1).startswith(table + ".")
            if not inside and start is not None:
                break
            if inside and start is None:
                start = i
        if start is not None and line.strip() and not line.lstrip().startswith("#"):
            end = i + 1
    return None if start is None else (start, end)


def apply(text: str, *, platform: str | None = None, infra: str | None = None) -> str:
    """`text` with its [platform] and/or [infra] tables replaced (or [infra] added after [platform]); every
    other line is kept. The result must still be a valid configuration."""
    lines = text.split("\n")
    for table, block in (("platform", platform), ("infra", infra)):
        if block is None:
            continue
        new = block.split("\n")
        r = _region(lines, table)
        if r is not None:
            lines[r[0] : r[1]] = new
        elif table == "infra":
            p = _region(lines, "platform")
            if p is None:
                raise ConfigError([f"{CONFIG_FILENAME} has no [platform] table"])
            lines[p[1] : p[1]] = ["", *new]
        else:
            raise ConfigError([f"{CONFIG_FILENAME} has no [platform] table"])
    out = "\n".join(lines)
    try:
        parse(tomllib.loads(out))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError([f"the proposed {CONFIG_FILENAME} is not valid TOML: {e}"]) from None
    return out


def diff(old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            f"a/{CONFIG_FILENAME}",
            f"b/{CONFIG_FILENAME}",
        )
    )
