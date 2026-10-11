"""GitHub dependency-submission snapshot for a platform release's tool components (issue #6).

Custom TOML pins are invisible to GitHub's dependency graph. Tool components that carry a package URL in
the toolchain manifest (e.g. `pkg:pypi/ruff@0.17.0`) can be submitted so that ecosystems GitHub's advisory
database covers get native Dependabot alerts. Components with other purl types are submitted too (they
appear in the graph) but cannot alert; `alert_capable_components` counts the ones that can, so nobody
mistakes the graph for coverage. The snapshot is data: this module never talks to GitHub.
"""

from __future__ import annotations

# purl types the GitHub Advisory Database covers (an alert needs one of these; everything else only shows up).
ALERT_ECOSYSTEMS = {
    "pypi",
    "npm",
    "cargo",
    "golang",
    "maven",
    "nuget",
    "gem",
    "composer",
    "swift",
    "pub",
    "actions",
}
DETECTOR = {"name": "dev-platform", "url": "https://github.com/syncom-systems/dev-platform"}


def purl_type(purl: str) -> str:
    return purl.removeprefix("pkg:").split("/", 1)[0]


def components(manifest: dict, profiles: list[str] | None = None) -> dict[str, dict]:
    """purl -> {name, profiles, alert_capable} for every tool pin that declares a purl."""
    out: dict[str, dict] = {}
    for pname, prof in sorted(manifest["profiles"].items()):
        if profiles and pname not in profiles:
            continue
        for tname, spec in sorted(prof["tools"].items()):
            purl = spec.get("purl")
            if not purl or "@" not in purl:  # an unversioned purl names no release; skip it
                continue
            c = out.setdefault(
                purl, {"name": tname, "profiles": [], "alert_capable": purl_type(purl) in ALERT_ECOSYSTEMS}
            )
            c["profiles"].append(pname)
    return out


def snapshot(
    manifest: dict,
    *,
    platform_version: str,
    sha: str,
    ref: str,
    scanned: str,
    job_id: str,
    correlator: str = "dev-platform-toolchain",
    profiles: list[str] | None = None,
    manifest_file: str = "toolchains/manifest.json",
    detector_version: str | None = None,
) -> dict:
    comps = components(manifest, profiles)
    resolved = {
        purl: {"package_url": purl, "relationship": "direct", "scope": "development"}
        for purl in sorted(comps)
    }
    return {
        "version": 0,
        "sha": sha,
        "ref": ref,
        "job": {"correlator": correlator, "id": job_id},
        "detector": {**DETECTOR, "version": detector_version or platform_version},
        "scanned": scanned,
        "metadata": {
            "platform_version": platform_version,
            "alert_capable_components": sum(c["alert_capable"] for c in comps.values()),
        },
        "manifests": {
            "dev-platform-toolchain": {
                "name": "dev-platform-toolchain",
                "file": {"source_location": manifest_file},
                "resolved": resolved,
            }
        },
    }
