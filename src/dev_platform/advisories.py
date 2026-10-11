"""Advisory impact analysis: which platform releases, consumers and supported lines an advisory touches,
what already fixes it, and which patch candidates to build. Descriptive: it proposes work, it publishes and
approves nothing (releases still go through release.yml, the verifier and, for acceptance, the owner)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from . import lifecycle, records
from .errors import ConfigError


def _components(rel: dict, ver: str) -> dict[str, str]:
    comps = {c["name"]: c["version"] for c in rel.get("sbom_doc", {}).get("components", [])}
    comps["dev-platform"] = ver
    return comps


def impact(advisory: dict, releases: dict[str, dict], consumer_pins: dict[str, str], policy: dict) -> dict:
    """releases: version -> {sbom_doc, prerelease?}. consumer_pins: consumer name -> platform version."""
    problems = records.validate_advisory(advisory)
    if problems:
        raise ConfigError(problems)
    hit = records.releases_affected(advisory, releases)
    stable = sorted(
        (v for v, r in releases.items() if not r.get("prerelease") and lifecycle.parse_version(v)[3] is None),
        key=lifecycle._precedence,
    )
    supported = lifecycle.supported_lines(stable, policy)
    entries = []
    for ver in sorted(hit, key=lifecycle._precedence):
        rel = releases[ver]
        later_fixed = next(
            (
                v
                for v in stable
                if lifecycle._precedence(v) > lifecycle._precedence(ver)
                and v not in hit
                and not rel.get("prerelease")
            ),
            None,
        )
        a, b, _, _ = lifecycle.parse_version(ver)
        line = f"{a}.{b}"
        if rel.get("prerelease"):
            action = {"action": "ignore-prerelease", "reason": "pre-releases are not used by consumers"}
        elif later_fixed:
            action = {"action": "upgrade", "to": later_fixed, "reason": "a later release is not affected"}
        elif line in supported:
            plan = lifecycle.patch_plan([ver], stable, policy)[0]
            comps = sorted({h.split("@")[0] for h in hit[ver]})
            kinds = ["security-fix"] + (["toolchain-patch"] if comps != ["dev-platform"] else [])
            action = {
                "action": "patch-release",
                "patch_version": plan["version"],
                "change_kinds": kinds,
                "reason": "supported line with no fixed release",
            }
        else:
            action = {"action": "no-patch-upgrade", "reason": f"line {line} is not supported"}
        entries.append({"version": ver, "affected_components": hit[ver], **action})
    consumers = {n: v for n, v in sorted(consumer_pins.items()) if v in hit}
    proposals = sorted(
        {(e["patch_version"], tuple(e["change_kinds"])) for e in entries if e["action"] == "patch-release"}
    )
    return {
        "advisory": advisory["id"],
        "severity": advisory["severity"],
        "supported_lines": supported,
        "releases": entries,
        "consumers": consumers,
        "patch_proposals": [
            {"version": v, "change_kinds": list(k), "milestone": f"v{v}"} for v, k in proposals
        ],
        "unaffected_releases": sorted((v for v in releases if v not in hit), key=lifecycle._precedence),
        "note": "proposals only: a patch release is built, verified and (separately) accepted through the "
        "normal pipeline; no advisory text approves anything",
    }


def github_releases(repo: str) -> dict[str, dict]:
    """version -> {sbom_doc, prerelease} from GitHub releases (read-only). `prerelease` means a version
    with a pre-release identifier; GitHub's flag also marks verified-unaccepted stable releases."""
    r = subprocess.run(
        ["gh", "release", "list", "--repo", repo, "--limit", "100", "--json", "tagName,isPrerelease"],
        capture_output=True,
        text=True,
    )
    if r.returncode:
        raise ConfigError([f"gh release list: {r.stderr.strip()[:200]}"])
    out = {}
    with tempfile.TemporaryDirectory() as td:
        for rel in json.loads(r.stdout):
            tag = rel["tagName"]
            ver = tag.removeprefix("v")
            d = Path(td) / tag
            d.mkdir()
            got = subprocess.run(
                ["gh", "release", "download", tag, "--repo", repo, "-D", str(d), "-p", "*.sbom.cdx.json"],
                capture_output=True,
                text=True,
            )
            f = next(d.glob("*.sbom.cdx.json"), None)
            if got.returncode or f is None:
                continue  # no SBOM asset (failed attempt): nothing to analyse
            out[ver] = {
                "sbom_doc": json.loads(f.read_text()),
                "prerelease": "-" in ver,
                "github_prerelease_flag": bool(rel["isPrerelease"]),
            }
    return out
