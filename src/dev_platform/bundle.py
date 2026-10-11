"""Immutable application-release evidence bundles (ADR 0019).

A bundle is a directory: the release record, the result records it names, every authorization record
(byte-for-byte, because authenticity is checked against the signed file) and any advisories, plus
`manifest.json` listing each file by sha256. The sha256 of the manifest is the single digest an operator
pins: it fixes every file, so a retained bundle is tamper-evident to anyone who holds that one value.
Bundles are write-once (existing directories are never reused) and files are made read-only. A new
decision (a revocation, say) is a NEW bundle whose `previous` names the old manifest digest; nothing is
edited in place.

This is local storage, not a trust anchor and not a compliance claim.
`tools/verify_app_release.py --bundle` is the independent reader.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

from . import records
from .errors import ConfigError

BUNDLE_SCHEMA = "dev-platform.app-release-evidence/v1"
CLASSES = (
    "standard",
    "extended",
    "regulated",
    "permanent",
)  # increasing; durations are the operator's policy


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retention_of(authorizations: list[dict]) -> dict:
    """Kept as long as the longest-lived record: highest class, latest `until` (null = indefinite)."""
    classes = [a["retention"]["class"] for a in authorizations] or ["standard"]
    unknown = sorted(set(classes) - set(CLASSES))
    if unknown:
        raise ConfigError([f"unknown retention class {unknown} (known: {list(CLASSES)})"])
    untils = [a["retention"]["until"] for a in authorizations] or [None]
    until = None if None in untils else max(untils)
    return {"class": max(classes, key=CLASSES.index), "until": until}


def build(
    out: Path,
    release: Path,
    *,
    results: list[Path] = (),
    authorizations: list[Path] = (),
    advisories: list[Path] = (),
    sbom: Path | None = None,
    previous: str | None = None,
) -> str:
    """Write a new bundle at `out` (must not exist). Returns the manifest sha256 to pin."""
    out = Path(out)
    if out.exists():
        raise ConfigError([f"{out} exists: bundles are write-once"])
    rel_doc = json.loads(Path(release).read_text())
    errs = records.validate_app_release(rel_doc)
    if errs:
        raise ConfigError([f"release record invalid: {e}" for e in errs])
    auth_docs = [json.loads(Path(a).read_text()) for a in authorizations]
    release_sha = records.canonical_digest(rel_doc)
    for a in auth_docs:
        if a.get("subject", {}).get("digest") != release_sha:
            raise ConfigError([f"authorization {a.get('id')} is not about this release record"])
    named = {e["sha256"] for e in rel_doc["evidence"]}
    have = {}
    for r in results:
        have[records.canonical_digest(json.loads(Path(r).read_text()))] = Path(r)
    missing = sorted(named - set(have))
    if missing:
        raise ConfigError([f"evidence not supplied: {m[:12]}" for m in missing])
    entries: list[tuple[str, str, Path]] = [("release", "release.json", Path(release))]
    entries += [("result", f"results/{d}.json", have[d]) for d in sorted(named)]
    for a, p in zip(auth_docs, authorizations, strict=True):
        if not re.match(r"^[A-Za-z0-9._-]+$", str(a["id"])):
            raise ConfigError([f"authorization id {a['id']!r} is not a safe file name"])
        entries.append(("authorization", f"authorizations/{a['id']}.json", Path(p)))
    entries += [("advisory", f"advisories/{Path(p).name}", Path(p)) for p in advisories]
    if sbom:
        entries.append(("sbom", "sbom.json", Path(sbom)))
    paths = [e[1] for e in entries]
    if len(paths) != len(set(paths)):
        raise ConfigError(["duplicate entry names in bundle"])
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "release_sha256": release_sha,
        "entries": [{"kind": k, "path": rel, "sha256": _sha(src)} for k, rel, src in entries],
        "retention": retention_of(auth_docs),
        "previous": previous,
    }
    tmp = out.with_name(out.name + ".partial")
    if tmp.exists():
        raise ConfigError([f"{tmp} exists from an interrupted build; remove it"])
    try:
        for _, rel, src in entries:
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            dest.chmod(stat.S_IRUSR)
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        (tmp / "manifest.json").chmod(stat.S_IRUSR)
        os.rename(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return _sha(out / "manifest.json")


def verify(directory: Path, manifest_sha256: str) -> list[str]:
    """Problems with a bundle against the operator's pin (empty = intact). Mirrors the independent reader."""
    root = Path(directory)
    try:
        raw = (root / "manifest.json").read_bytes()
        m = json.loads(raw)
    except (OSError, ValueError) as e:
        return [f"manifest unreadable: {e}"]
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        return ["manifest does not match the pin"]
    if m.get("schema") != BUNDLE_SCHEMA:
        return ["unknown manifest schema"]
    problems, listed = [], {"manifest.json"}
    for e in m.get("entries", []):
        f = root / e["path"]
        listed.add(e["path"])
        if f.is_symlink() or not f.is_file():
            problems.append(f"{e['path']}: missing")
        elif _sha(f) != e["sha256"]:
            problems.append(f"{e['path']}: bytes differ")
    present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    problems += [f"{x}: not listed" for x in sorted(present - listed)]
    return problems
