"""`dev-platform workflow`: the GitHub Actions workflow a project would add, as a proposal (ADR 0023).

It renders a caller of the reusable `consumer-pilot.yml` at the project's pinned platform release, on a
GitHub-hosted runner: no infrastructure repository, provider, credential or self-hosted runner is involved. It
prints to stdout; `--output` writes a new file and never overwrites one. It never commits, pushes, enables a
workflow or changes a repository setting: the workflow becomes active only when someone commits it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dev_platform.config import CONFIG_FILENAME, load
from dev_platform.errors import ConfigError
from dev_platform.infra_config import GITHUB_HOSTED, looks_hosted

PINS_FILENAME = "dev-platform.release-pins.json"
REUSABLE = "syncom-systems/dev-platform/.github/workflows/consumer-pilot.yml"
FIRST_REUSABLE = (0, 8, 2)  # earlier releases' reusable workflow is defective (CHANGELOG 0.8.2)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
PROVISIONABLE = {("linux", "x86_64"), ("macos", "arm64")}  # platforms toolchain profiles have sources for


def _pins(project: Path) -> dict:
    p = project / PINS_FILENAME
    pin = load(project).platform
    try:
        # the identity lives in dev-platform.toml from 0.17.0; the pins file is the older place
        pins = (
            {"version": pin.version, "source_revision": pin.source_revision}
            if pin.source_revision
            else json.loads(p.read_text())
        )
    except OSError:
        raise ConfigError([f"no {p}: pin a platform release first (docs/consumer-integration.md)"]) from None
    except ValueError as e:
        raise ConfigError([f"{p}: {e}"]) from None
    version, rev = pins.get("version"), pins.get("source_revision")
    if not isinstance(version, str) or not isinstance(rev, str) or not _SHA.fullmatch(rev):
        raise ConfigError([f"{p}: needs version and a full source_revision"])
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.]+)?", version)  # it is written into the workflow
    if not m or tuple(int(x) for x in m.groups()[:3]) < FIRST_REUSABLE:
        raise ConfigError(
            [f"{p}: release {version} predates a working reusable workflow; pin 0.8.2 or later"]
        )
    return pins


def render(
    project: Path, runs_on: str = "ubuntu-24.04", branch: str = "main", allow_unaccepted: bool = False
) -> tuple[str, list[str]]:
    """(workflow text, notes). Refuses anything that is not a GitHub-hosted image label."""
    if not (project / CONFIG_FILENAME).is_file():
        raise ConfigError([f"no {project / CONFIG_FILENAME}: run `dev-platform init` first"])
    if (
        not _LABEL.fullmatch(runs_on)
        or not looks_hosted([runs_on])
        or not runs_on.startswith(("ubuntu-", "macos-"))
    ):
        raise ConfigError(
            [
                f"runs_on {runs_on!r}: the preview proposes GitHub-hosted runners only (for example "
                f"{', '.join(h['labels'][0] for h in GITHUB_HOSTED)}); self-hosted runners are an "
                "organization's "
                "explicit decision (dev-platform infra init --template self-hosted)"
            ]
        )
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", branch):
        raise ConfigError([f"branch {branch!r}: a plain branch name"])
    pins = _pins(project)
    notes = []
    known = next((h for h in GITHUB_HOSTED if h["labels"] == [runs_on]), None)
    if known is None:
        notes.append(
            f"{runs_on}: not one of the validated examples; check the platform's toolchain profile has "
            "sources"
        )
    elif (known["os"], known["arch"]) not in PROVISIONABLE:
        notes.append(
            f"{runs_on} is {known['os']}-{known['arch']}: toolchain profiles have sources for "
            "linux-x86_64 and macos-arm64 only, provisioning will fail"
        )
    if allow_unaccepted:
        notes.append(
            "allow_unaccepted: the pinned release was published before 0.12.0 as verified-unaccepted "
            "(your decision)"
        )
    rev, version = pins["source_revision"], pins["version"]
    text = f"""\
# Proposed by `dev-platform workflow`: review it, then commit it yourself. Nothing is active until it is
# committed; it is an additional job, not a required check unless you make it one. It runs the project's
# pinned platform release ({version}) on a GitHub-hosted runner with a read-only token and calls no
# infrastructure provider, so it is safe for pull requests from forks.
name: dev-platform
on:
  pull_request:
  push:
    branches: [{branch}]
permissions:
  contents: read
jobs:
  dev-platform:
    uses: {REUSABLE}@{rev}  # v{version}
    with:
      platform_source_revision: "{rev}"
      allow_unaccepted: {str(allow_unaccepted).lower()}
      runs_on: {runs_on}
"""
    return text, notes


def write_new(path: Path, text: str) -> None:
    """Create `path`; an existing file (or symlink) is never replaced."""
    with open(path, "x") as f:
        f.write(text)


__all__ = ["render", "write_new"]
