"""Platform version resolution and integrity verification (the launcher core).

No global mutable state: versions live side by side, immutable, in a store the
launcher only reads. A consumer pins an exact version plus a tree digest.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import dev_platform
from dev_platform import release as releases
from dev_platform.config import Config
from dev_platform.digest import snapshot, tree_digest
from dev_platform.errors import ConfigError, PlatformResolutionError
from dev_platform.locations import HOME_ENV, STORE_ENV

OVERRIDE_ENV = "DEV_PLATFORM_OVERRIDE"
REEXEC_ENV = "DEV_PLATFORM_REEXEC"
PYTHON_ENV = "DEV_PLATFORM_PYTHON"
PACKAGE_ROOT = Path(dev_platform.__file__).resolve().parent.parent  # .../src


@dataclass(frozen=True)
class Resolution:
    mode: str  # "pinned" | "override" | "self"
    version: str | None
    root: Path | None  # directory containing the dev_platform package (a `src` dir)
    digest: str | None
    release: dict | None = None  # release.json (or a synthesized view for self/override)
    cleanup: Path | None = None  # private snapshot directory to delete after use

    @property
    def certifiable(self) -> bool:
        # A self-hosted result cannot establish that the platform release is trustworthy
        # (ADR 0014); only a release verified against an independent pin is certifiable.
        return self.mode == "pinned"

    def dispose(self) -> None:
        if self.cleanup:
            shutil.rmtree(self.cleanup, ignore_errors=True)


def protected_context(env=os.environ, flag: bool = False) -> bool:
    return flag or env.get("CI", "").lower() in ("1", "true") or env.get("GITHUB_ACTIONS") == "true"


def default_store(env=os.environ) -> Path:
    if env.get(STORE_ENV):
        return Path(env[STORE_ENV])
    if env.get(HOME_ENV):
        return Path(env[HOME_ENV]) / "versions"
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "dev-platform" / "versions"


def resolve(cfg: Config, *, env=os.environ, protected: bool = False) -> Resolution:
    override = env.get(OVERRIDE_ENV)
    if override:
        if protected_context(env, protected):
            raise PlatformResolutionError(
                f"{OVERRIDE_ENV} is set in a protected context (CI or --protected); "
                "overrides may not influence protected runs or certification"
            )
        root = Path(override) / "src"
        if not (root / "dev_platform").is_dir():
            raise PlatformResolutionError(f"{OVERRIDE_ENV}={override}: no src/dev_platform inside")
        return Resolution(
            "override", None, root.resolve(), None, releases.synthesize_for_checkout(Path(override))
        )

    pin = cfg.platform
    if pin.self_hosted:
        return Resolution(
            "self",
            dev_platform.__version__,
            PACKAGE_ROOT,
            None,
            releases.synthesize_for_checkout(PACKAGE_ROOT.parent),
        )

    if env.get(REEXEC_ENV):
        # We are the child of a verifying launcher. Re-verify the tree we are actually running
        # from (a private snapshot), so the code in use is the code the pin names.
        vdir = PACKAGE_ROOT.parent
        try:
            actual = tree_digest(vdir)
        except (OSError, ValueError) as e:
            raise PlatformResolutionError(f"cannot digest running release {vdir}: {e}") from None
        if actual != pin.sha256:
            raise PlatformResolutionError("running release does not match the pinned digest")
        return Resolution("pinned", pin.version, PACKAGE_ROOT, actual, _load_release(vdir))

    vdir = default_store(env) / pin.version
    if not vdir.is_dir():
        raise PlatformResolutionError(
            f"platform {pin.version} is not installed in {vdir.parent} (fetch it with the "
            "launcher/bootstrap documented in docs/distribution.md)"
        )
    # Verify-then-use without a race: copy the release into a private directory while hashing the
    # exact bytes copied, compare to the pin, and execute only from that copy.
    snap = Path(tempfile.mkdtemp(prefix="dev-platform-"))
    try:
        actual = snapshot(vdir, snap / "release")
        if actual != pin.sha256:
            raise PlatformResolutionError(
                f"integrity failure for platform {pin.version}: pinned sha256 {pin.sha256}, "
                f"installed tree is {actual}"
            )
        root = snap / "release" / "src"
        if not (root / "dev_platform").is_dir():
            raise PlatformResolutionError(f"{vdir}: malformed release (no src/dev_platform)")
        return Resolution(
            "pinned", pin.version, root.resolve(), actual, _load_release(snap / "release"), cleanup=snap
        )
    except (OSError, ValueError) as e:
        shutil.rmtree(snap, ignore_errors=True)
        raise PlatformResolutionError(f"cannot snapshot {vdir}: {e}") from None
    except PlatformResolutionError:
        shutil.rmtree(snap, ignore_errors=True)
        raise


def _load_release(vdir: Path) -> dict:
    try:
        return releases.load(vdir)
    except ConfigError as e:
        raise PlatformResolutionError(f"invalid release: {e}") from None


def needs_reexec(res: Resolution, env=os.environ) -> bool:
    """True when the resolved release is not the code currently running.

    Raises if we were already re-executed and still do not match (no loops).
    """
    if res.root is None or res.root == PACKAGE_ROOT:
        return False
    if env.get(REEXEC_ENV):
        raise PlatformResolutionError(
            f"re-executed into {env[REEXEC_ENV]} but running code is {PACKAGE_ROOT}, not {res.root}"
        )
    return True


def reexec_env(res: Resolution, env=os.environ) -> dict[str, str]:
    e = dict(env)
    e["PYTHONPATH"] = str(res.root)
    e["PYTHONDONTWRITEBYTECODE"] = "1"  # keep the pinned tree byte-identical
    e[REEXEC_ENV] = res.version or res.mode
    return e


def reexec_python(env=os.environ) -> str:
    """The interpreter the pinned release runs on: `DEV_PLATFORM_PYTHON` (`dev-platform setup` sets it to a
    profile's provisioned python), else this one. Only a selection: the release verifies the interpreter it
    runs on against its manifest, so a wrong one yields a non-conformant environment, never a certified
    result."""
    exe = env.get(PYTHON_ENV)
    if not exe:
        return sys.executable
    if not (os.path.isfile(exe) and os.access(exe, os.X_OK)):
        raise PlatformResolutionError(f"{PYTHON_ENV}={exe} is not an executable file")
    return exe
