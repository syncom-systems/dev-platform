"""Immutable infrastructure configuration releases and their index (ADR 0023).

An organization's infrastructure configuration is frozen into releases that a consumer pins exactly
(`[infra] config_release` + `config_digest`, ADR 0021). The layout of a configuration repository or store:

    releases/index.v1.json            {"schema_version": 1, "releases": [{version, digest, contract}]}
    releases/<YYYY.MM.N>/             one immutable release (CalVer, independent of platform SemVer)
        manifest.json                 format, version, contract, owner, repositories
        profiles/<repository>.json    the dev-platform.infra/v1 profile computed at build time
        ...                           any further declared configuration (part of the identity, opaque here)

**Identity** is the version plus the release-tree digest: `sha256:` + the platform's `tree_digest` of the
release directory (length-prefixed relative path and content, canonical order). It is the identity of the
whole release, not of a profile file; a profile's own digest (`effective_profile_digest`) is a different
value and changes when the current authorization policy narrows a release. The index stores bare hex,
outside the tree, so the digest is never part of what it covers. A release tree must be plain data:
symlinks, special files, `__pycache__` and `*.pyc` are refused, which also makes this digest equal to
`tree_digest` for every tree accepted here.

Releases are immutable by construction: `build` refuses an existing or older version, `verify` checks every
indexed release against its digest, flags unindexed directories, and against a base index (the protected
branch) allows entries to be added only, never changed or removed.

`FORMATS` lists every release format this platform can resolve and the profile contract each implements.
Formats are only ever added, so a newer platform resolves every older release unchanged (its bytes are never
rewritten).
"""

from __future__ import annotations

import json
import os
import re
import stat
from hashlib import sha256
from pathlib import Path

from dev_platform.digest import _feed
from dev_platform.errors import ConfigError
from dev_platform.runners import INFRA_SCHEMA

FORMAT = "dev-platform.infra-config-release/v1"
# Releases built before the public tooling existed: same layout, the owner is the `org` of org.json.
LEGACY_FORMATS = {"dpinfra.config-release/v1": "org.json"}
FORMATS = {FORMAT: INFRA_SCHEMA, **dict.fromkeys(LEGACY_FORMATS, INFRA_SCHEMA)}
INDEX = "releases/index.v1.json"
VERSION_RE = re.compile(r"^(\d{4})\.(0[1-9]|1[0-2])\.(0|[1-9]\d{0,3})$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
WIRE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_REFUSED = ("__pycache__",)


class ReleaseError(ConfigError):
    """A refusal with a stable code (the provider's denial code)."""

    def __init__(self, code: str, detail: str):
        super().__init__([f"{code}: {detail}"])
        self.code, self.detail = code, detail


def version_key(v: object) -> tuple[int, int, int]:
    """CalVer `YYYY.MM.N` (month 01-12, N without leading zeros) as a sortable key."""
    m = VERSION_RE.fullmatch(v) if isinstance(v, str) else None
    if not m:
        raise ReleaseError("version-invalid", f"configuration release {v!r}: expected YYYY.MM.N")
    return int(m[1]), int(m[2]), int(m[3])


def in_tree_order(files: dict[str, bytes]) -> dict[str, bytes]:
    """`files` in the order `tree_digest` walks a directory: at each level its files by name, then its
    subdirectories by name. A release received in memory therefore digests exactly as it would on disk."""

    def key(rel: str):
        *dirs, name = rel.split("/")
        return [(1, d) for d in dirs] + [(0, name)]

    return {rel: files[rel] for rel in sorted(files, key=key)}


def digest_of(files: dict[str, bytes]) -> str:
    """Bare hex release-tree digest of exactly these bytes (what is verified is what is parsed)."""
    h = sha256()
    for rel, data in in_tree_order(files).items():
        _feed(h, rel, data)
    return h.hexdigest()


def _refuse(rel: str) -> str | None:
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return f"{rel}: not a plain relative path"
    if any(p in _REFUSED for p in parts) or rel.endswith(".pyc"):
        return f"{rel}: generated files are not configuration"
    return None


def check_files(files: dict[str, bytes]) -> None:
    for rel in files:
        if why := _refuse(rel):
            raise ReleaseError("release-tampered", why)


def read_tree(root: Path) -> dict[str, bytes]:
    """All files of a release directory. Anything but plain directories and regular files is refused:
    `release-unreadable` when the content cannot be read as plain files (a symlink, a special file, no
    directory), `release-tampered` when it holds what a release never contains (generated files)."""
    root = Path(root)
    if root.is_symlink():
        raise ReleaseError("release-unreadable", f"{root}: is a symlink")
    if not root.is_dir():
        raise ReleaseError("release-unreadable", f"{root}: no release directory")
    out: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for n in [*dirnames, *filenames]:
            p = Path(dirpath) / n
            rel = p.relative_to(root).as_posix()
            mode = os.lstat(p).st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ReleaseError("release-unreadable", f"{rel}: symlink or special file")
            if why := _refuse(rel):
                raise ReleaseError("release-tampered", why)
        dirnames.sort()
        for n in sorted(filenames):
            p = Path(dirpath) / n
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return in_tree_order(out)


def canonical(doc: object) -> bytes:
    """The serialization of every JSON document a release build writes."""
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()


def index_bytes(idx: dict) -> bytes:
    return (json.dumps(idx, indent=2) + "\n").encode()


def empty_index() -> dict:
    return {"schema_version": 1, "releases": []}


def check_index(idx: object) -> dict:
    """{"schema_version": 1, "releases": [{"version", "digest" (bare hex), "contract"}]}, nothing else."""
    if (
        not isinstance(idx, dict)
        or idx.get("schema_version") != 1
        or set(idx) != {"schema_version", "releases"}
        or not isinstance(idx["releases"], list)
    ):
        raise ReleaseError("index-invalid", "release index: schema_version 1 with only 'releases'")
    seen: set[str] = set()
    for r in idx["releases"]:
        if not isinstance(r, dict) or set(r) != {"version", "digest", "contract"}:
            raise ReleaseError("index-invalid", f"release index: bad entry {r!r}")
        version_key(r["version"])
        if r["version"] in seen:
            raise ReleaseError("index-invalid", f"release index: duplicate {r['version']}")
        if not isinstance(r["digest"], str) or not HEX_RE.fullmatch(r["digest"]):
            raise ReleaseError("index-invalid", f"release index: bad digest for {r['version']}")
        if not isinstance(r["contract"], str):
            raise ReleaseError("index-invalid", f"release index: bad contract for {r['version']}")
        seen.add(r["version"])
    return idx


def load_index(path: Path) -> dict:
    try:
        return check_index(json.loads(Path(path).read_bytes()))
    except OSError as e:
        raise ReleaseError("index-invalid", f"{path}: {e.strerror or e}") from None
    except ValueError as e:
        raise ReleaseError("index-invalid", f"{path}: {e}") from None


def wire(hexdigest: str) -> str:
    return "sha256:" + hexdigest


def manifest_of(files: dict[str, bytes], version: str, contract: str) -> tuple[dict, str]:
    """(manifest, owner) of a verified release, or a refusal: the format must be one this platform resolves,
    implement `contract`, and name `version` and an owner."""
    try:
        manifest = json.loads(files["manifest.json"])
    except (KeyError, ValueError):
        raise ReleaseError("unsupported-format", "manifest.json missing or unreadable") from None
    fmt = manifest.get("schema") if isinstance(manifest, dict) else None
    if not isinstance(fmt, str) or FORMATS.get(fmt) != contract or manifest.get("contract") != contract:
        supported = ", ".join(f"{k} ({v})" for k, v in FORMATS.items())
        raise ReleaseError("unsupported-format", f"{fmt!r} for {contract!r}; supported: {supported}")
    if manifest.get("version") != version:
        raise ReleaseError("unsupported-format", f"manifest names {manifest.get('version')!r}, not {version}")
    repos = manifest.get("repositories")
    if not (isinstance(repos, list) and all(isinstance(r, str) and REPO_NAME_RE.fullmatch(r) for r in repos)):
        raise ReleaseError("unsupported-format", "manifest.repositories: list of repository names")
    if fmt in LEGACY_FORMATS:
        try:
            owner = json.loads(files[LEGACY_FORMATS[fmt]])["org"]
        except (KeyError, ValueError, TypeError):
            raise ReleaseError("unsupported-format", f"{LEGACY_FORMATS[fmt]} has no owner") from None
    else:
        owner = manifest.get("owner")
    if not isinstance(owner, str) or not OWNER_RE.fullmatch(owner):
        raise ReleaseError("unsupported-format", "release names no valid owner")
    return manifest, owner


def make_manifest(version: str, owner: str, repositories: list[str], sources: dict | None = None) -> dict:
    doc = {
        "schema": FORMAT,
        "version": version,
        "contract": INFRA_SCHEMA,
        "owner": owner,
        "repositories": sorted(repositories),
    }
    if sources:
        doc["sources"] = sources
    return doc


def build(root: Path, version: str, files: dict[str, bytes]) -> str:
    """Write `files` as the new release `version` under `root` and append it to the index. Returns the bare
    hex digest. Refuses an existing or older version, a malformed manifest or an invalid profile."""
    from dev_platform.runners import validate_profile

    version_key(version)
    check_files(files)
    manifest, _ = manifest_of(files, version, INFRA_SCHEMA)
    for name in manifest["repositories"]:
        try:
            prof = json.loads(files[f"profiles/{name}.json"])
        except (KeyError, ValueError):
            raise ReleaseError("unsupported-format", f"profiles/{name}.json missing or unreadable") from None
        if problems := validate_profile(prof):
            raise ReleaseError("profile-invalid", f"profiles/{name}.json: {'; '.join(problems)}")
    idx_path = Path(root) / INDEX
    idx = load_index(idx_path) if idx_path.exists() else empty_index()
    if any(r["version"] == version for r in idx["releases"]):
        raise ReleaseError("release-exists", f"{version} already exists; releases are immutable")
    if idx["releases"] and version_key(version) <= max(version_key(r["version"]) for r in idx["releases"]):
        raise ReleaseError("release-not-newer", f"{version} must be newer than every existing release")
    dest = Path(root) / "releases" / version
    if dest.exists() or dest.is_symlink():
        raise ReleaseError(
            "release-exists", f"{dest} exists but is not indexed; remove it or pick another version"
        )
    for rel, data in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    digest = digest_of(read_tree(dest))
    if digest != digest_of(files):
        raise ReleaseError("release-tampered", f"{dest}: written content differs from what was built")
    idx["releases"].append({"version": version, "digest": digest, "contract": INFRA_SCHEMA})
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_bytes(index_bytes(idx))
    return digest


def verify(root: Path, base_index: dict | None = None) -> list[str]:
    """Problems with the releases under `root` (empty: all good). With `base_index` (the protected branch's),
    the index may only have grown."""
    errs: list[str] = []
    try:
        idx = load_index(Path(root) / INDEX)
    except ReleaseError as e:
        return [e.detail]
    listed = {r["version"]: r for r in idx["releases"]}
    for v, r in listed.items():
        try:
            files = read_tree(Path(root) / "releases" / v)
            if digest_of(files) != r["digest"]:
                errs.append(f"{v}: release-tree digest differs from the index (release modified)")
                continue
            manifest_of(files, v, r["contract"])
        except ReleaseError as e:
            errs.append(f"{v}: {e.code}: {e.detail}")
    rel_dir = Path(root) / "releases"
    for d in sorted(rel_dir.iterdir()) if rel_dir.is_dir() else ():
        if d.is_dir() and d.name not in listed:
            errs.append(f"{d.name}: release directory not in the index")
    if base_index is not None:
        for r in check_index(base_index)["releases"]:
            if listed.get(r["version"]) != r:
                errs.append(f"{r['version']}: indexed release changed or removed relative to the base index")
    return errs


__all__ = [
    "FORMAT",
    "FORMATS",
    "INDEX",
    "ReleaseError",
    "build",
    "canonical",
    "check_index",
    "digest_of",
    "load_index",
    "make_manifest",
    "manifest_of",
    "read_tree",
    "verify",
    "version_key",
]
