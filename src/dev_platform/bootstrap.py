"""The bootstrap contract: what a launcher may rely on in a release, and nothing more.

A launcher (the CLI that runs `dev-platform setup`) installs and verifies a project's pinned release with the
trusted installer, runs it from a verified private snapshot, and lets that release validate its own toolchain
manifest and prepare its own environment. It never interprets a manifest of a release it is about to run.

A release declares the contract it implements in `src/dev_platform/bootstrap-contract.json`
(`{"contract": N}`), inside the tree whose digest the project pins. Contract 1 is the single command

    python -P -m dev_platform toolchain prepare --project P --profile X --dest D

run from the snapshot with the re-execution environment; it prints one JSON record (`ok`, and on success the
profile directory's state, on failure `problem` and `exit`) and exits 0 only for a conformant, certifiable
environment. Releases 0.8.0 to 0.14.0 predate the declaration: the launcher drives them through the frozen
adapter in `projectsetup` (`prepare.prepare` over the manifest in their `release.json`, read, not validated).
A release that declares a contract this launcher does not implement is refused before anything of it runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CONTRACT = 1  # the highest contract this code implements, as a launcher and as a release
DECLARATION = "dev_platform/bootstrap-contract.json"  # under the release's src/
LEGACY_BEFORE = (0, 15, 0)  # releases older than this have no declaration
_VER = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


class ContractError(Exception):
    pass


def declared(src: Path) -> int | None:
    """The contract the release whose `src` directory this is declares; None when it has no declaration."""
    f = Path(src) / DECLARATION
    if not f.is_file():
        return None
    try:
        n = json.loads(f.read_text())["contract"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ContractError(f"{f}: not a valid bootstrap contract declaration") from None
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ContractError(f"{f}: contract must be a positive integer")
    return n


def select(src: Path, version: str) -> int | None:
    """The contract to drive the verified release `version` with: 1.. for a declaring release, None for the
    frozen legacy adapter. Raises ContractError for a release that must declare one and does not, or that
    declares one this launcher does not implement."""
    n = declared(src)
    m = _VER.match(version)
    older = bool(m) and tuple(int(x) for x in m.groups()) < LEGACY_BEFORE
    if n is None:
        if older:
            return None
        raise ContractError(f"release {version} declares no bootstrap contract")
    if n > CONTRACT:
        raise ContractError(
            f"release {version} requires bootstrap contract {n}; this dev-platform CLI implements "
            f"contract {CONTRACT}: install a newer CLI (docs/distribution.md#upgrading-the-cli); the "
            "release was not executed"
        )
    return n
