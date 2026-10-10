"""Platform release build and verification (dev-platform.release/v1) and SBOM generation.

A release is an immutable directory:
    <version>/src/dev_platform/...   the orchestration code
    <version>/release.json           identity: toolchain manifest, source digest, SBOM digest, provenance
    <version>/sbom.cdx.json          CycloneDX component inventory
Its tree digest is what consumers pin. release.json holds no timestamps, so builds are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from dev_platform import toolchain
from dev_platform.digest import tree_digest
from dev_platform.errors import ConfigError

RELEASE_SCHEMA = "dev-platform.release/v1"
PURL_NAME = "pkg:github/syncom-systems/dev-platform"


def _dump(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def make_sbom(version: str, source_digest: str, manifest: dict) -> dict:
    components, seen = [], set()
    for pname in sorted(manifest["profiles"]):
        for tname, spec in sorted(manifest["profiles"][pname]["tools"].items()):
            key = (tname, spec["version"])
            if key in seen:
                continue
            seen.add(key)
            comp = {
                "type": "application",
                "name": tname,
                "version": spec["version"],
                "bom-ref": f"tool:{tname}@{spec['version']}",
            }
            if spec.get("purl"):
                comp["purl"] = spec["purl"]
            sha = spec.get("sha256")
            if isinstance(sha, str):
                comp["hashes"] = [{"alg": "SHA-256", "content": sha}]
            components.append(comp)
    return {
        "bomFormat": "CycloneDX",
        # Deterministic serial (required by attest-sbom): derived from the identity it describes.
        "serialNumber": "urn:uuid:"
        + str(uuid.uuid5(uuid.NAMESPACE_URL, f"{PURL_NAME}@{version}:{source_digest}")),
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "dev-platform",
                "version": version,
                "bom-ref": f"{PURL_NAME}@{version}",
                "purl": f"{PURL_NAME}@{version}",
                "hashes": [{"alg": "SHA-256", "content": source_digest}],
            }
        },
        "components": components,
    }


def build(
    src_root: Path,
    toolchains: Path,
    out_dir: Path,
    version: str,
    *,
    source_uri: str | None = None,
    source_revision: str | None = None,
    strict_version: bool = True,
) -> Path:
    """Create out_dir/<version>/. Refuses to overwrite: releases are write-once."""
    dest = Path(out_dir) / version
    if dest.exists():
        raise ConfigError([f"{dest} exists; releases are immutable (use a new version)"])
    manifest = toolchain.validate(json.loads(Path(toolchains).read_text()))
    if strict_version:
        m = re.search(
            r'^__version__ = "([^"]+)"', (Path(src_root) / "dev_platform" / "__init__.py").read_text(), re.M
        )
        if not m or m.group(1) != version:
            raise ConfigError([f"source __version__ {m and m.group(1)!r} != release version {version!r}"])
    shutil.copytree(src_root, dest / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    source_digest = tree_digest(dest / "src")
    sbom = _dump(make_sbom(version, source_digest, manifest))
    (dest / "sbom.cdx.json").write_text(sbom)
    release = {
        "schema": RELEASE_SCHEMA,
        "platform": {"name": "dev-platform", "version": version, "source_digest": source_digest},
        "toolchains": manifest,
        "sbom": {"path": "sbom.cdx.json", "sha256": hashlib.sha256(sbom.encode()).hexdigest()},
        "provenance": {
            "source_uri": source_uri,
            "source_revision": source_revision,
            "attestations": [],
        },  # filled by the release workflow, see docs/supply-chain.md
    }
    (dest / "release.json").write_text(_dump(release))
    return dest


def load(release_dir: Path) -> dict:
    """Read and structurally verify release.json against the tree beside it."""
    d = Path(release_dir)
    try:
        doc = json.loads((d / "release.json").read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError([f"{d}/release.json: {e}"]) from None
    if doc.get("schema") != RELEASE_SCHEMA:
        raise ConfigError([f"{d}/release.json: schema must be {RELEASE_SCHEMA!r}"])
    toolchain.validate(doc.get("toolchains", {}))
    problems = []
    if tree_digest(d / "src") != doc["platform"]["source_digest"]:
        problems.append("src does not match platform.source_digest")
    sbom = d / doc["sbom"]["path"]
    if not sbom.is_file() or hashlib.sha256(sbom.read_bytes()).hexdigest() != doc["sbom"]["sha256"]:
        problems.append("SBOM missing or does not match sbom.sha256")
    if problems:
        raise ConfigError([f"release {d.name}: {p}" for p in problems])
    return doc


def synthesize_for_checkout(checkout: Path) -> dict | None:
    """Release-shaped view of a development checkout (self/override modes). Never certifiable."""
    f = Path(checkout) / "toolchains" / "manifest.json"
    if not f.is_file():
        return None
    return {
        "schema": RELEASE_SCHEMA,
        "synthesized": True,
        "platform": {"name": "dev-platform", "version": None, "source_digest": None},
        "toolchains": toolchain.validate(json.loads(f.read_text())),
    }
