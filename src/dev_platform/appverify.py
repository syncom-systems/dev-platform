"""Run the independent application-release verifier (tools/verify_app_release.py) under operator pins.

Like `lifecycle.run_verifier` for platform releases: this module is a *runner*, never an authority. The
verifier's bytes and the platform verifier's bytes (its provider registry) are checked against pins the
operator supplies from outside the repository under review; the verifier's record is the only thing consulted.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import records
from .errors import ConfigError

FUTURE_SKEW = timedelta(seconds=60)
VERIFICATION = "dev-platform.app-release-verification/v1"


def _pinned(path: Path, pin: str, what: str) -> None:
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if got != pin:
        raise ConfigError([f"{what} sha256 {got} does not match the pin {pin}"])


class AppVerifier:
    """Verifies one release at a time with the pinned independent verifier."""

    def __init__(
        self,
        verifier: Path,
        verifier_sha256: str,
        platform_verifier: Path,
        platform_verifier_sha256: str,
        policy: Path,
        *,
        results: dict[str, dict],
        authorizations: list[Path],
        advisories: list[Path] = (),
        platform_sbom: Path | None = None,
        mode: str = "select",
        platform_args: list[str] = (),
        audit_state: Path | None = None,
    ):
        _pinned(verifier, verifier_sha256, "application verifier")
        _pinned(platform_verifier, platform_verifier_sha256, "platform verifier")
        self.argv_base = [
            sys.executable,
            "-I",
            str(verifier),
            "--policy",
            str(policy),
            "--platform-verifier",
            str(platform_verifier),
            "--platform-verifier-sha256",
            platform_verifier_sha256,
            "--mode",
            mode,
        ]
        # --platform-archive/--platform-policy/... passed through verbatim: the verifier re-runs the platform
        # verifier for policies that require an accepted Dev Platform release (checked against its own pins).
        self.argv_base += list(platform_args)
        if audit_state:
            self.argv_base += ["--audit-state", str(audit_state)]
        self.results = results
        self.authorizations = list(authorizations)
        self.advisories = list(advisories)
        self.platform_sbom = platform_sbom

    @staticmethod
    def _current(rec: dict) -> None:
        """An approval counts for a current decision only if it read the current state, just now."""
        if rec.get("approval", {}).get("state") != "approved":
            return
        cur = rec.get("currency") or {}
        if cur.get("purpose") != "operational" or cur.get("status") != "current":
            raise ConfigError(["verifier record is not a current-state verification (fail closed)"])
        try:
            seen = datetime.fromisoformat(cur["observed_at"])
            until = datetime.fromisoformat(cur["valid_until"])
        except (KeyError, TypeError, ValueError):
            raise ConfigError(
                ["verifier record has no usable observed_at/valid_until (fail closed)"]
            ) from None
        now = datetime.now(UTC)
        if seen > now + FUTURE_SKEW or now > until:
            raise ConfigError(
                [
                    f"verification is not fresh (observed {cur['observed_at']}, "
                    f"valid until {cur['valid_until']})"
                ]
            )

    def __call__(self, release: dict) -> dict:
        """The verifier's record for `release`; a missing or malformed record is an error, never approval."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "release.json").write_text(json.dumps(release, sort_keys=True))
            argv = [*self.argv_base, str(td / "release.json"), "--out", str(td / "out.json")]
            for i, res in enumerate(self.results.values()):
                (td / f"result-{i}.json").write_text(json.dumps(res, sort_keys=True))
                argv += ["--result", str(td / f"result-{i}.json")]
            for a in self.authorizations:
                argv += ["--authorization", str(a)]
            for a in self.advisories:
                argv += ["--advisory", str(a)]
            if self.platform_sbom:
                argv += ["--platform-sbom", str(self.platform_sbom)]
            proc = subprocess.run(argv, capture_output=True, text=True)
            out = td / "out.json"
            if not out.is_file():
                raise ConfigError([f"application verifier produced no record: {proc.stderr.strip()[:200]}"])
            rec = json.loads(out.read_text())
        if rec.get("schema") != VERIFICATION:
            raise ConfigError([f"unexpected verifier record schema {rec.get('schema')!r}"])
        self._current(rec)
        if (rec.get("subject") or {}).get("release_sha256") != records.canonical_digest(release):
            raise ConfigError(["verifier record is not bound to the release that was submitted"])
        return rec
