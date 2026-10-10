"""Execution-environment scrubbing for check commands.

Tool identity says which bytes run; it says nothing about what the process inherits. By default a check
inherits the whole parent environment (credentials, proxies, tool-specific variables, a developer's HOME).
Scrubbed mode starts from an empty environment and adds only an allowlist, a PATH made of the verified
tools' own directories plus fixed system directories, and a private HOME/TMPDIR.

This is environment-variable isolation ONLY. It does not isolate the filesystem, network, processes or
kernel, and it does not make the run hermetic. The result records exactly what was passed (names, never
values) and states that limit.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ALLOW = (
    "LANG",
    "LC_ALL",
    "TZ",
    "TERM",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)
SYSTEM_PATH = ("/usr/bin", "/bin")
LIMITS = (
    "environment variables only: filesystem, network, processes and kernel are not isolated",
    "PATH is the verified tools' directories plus system directories; system tools are trusted by name",
)


def tool_dirs(names: list[str], path: str | None = None) -> list[str]:
    """Directory of each named tool as the current PATH resolves it (deduplicated, in order)."""
    out: list[str] = []
    for n in names:
        found = shutil.which(n, path=path)
        if found:
            d = str(Path(found).parent)
            if d not in out:
                out.append(d)
    return out


def scrub(
    base: dict[str, str], *, path_dirs: list[str], scratch: Path, keep: tuple[str, ...] = ()
) -> tuple[dict[str, str], dict]:
    """(environment, report). `keep` adds variable names to the allowlist (an explicit opt-in)."""
    allowed = sorted({*ALLOW, *keep})
    env = {k: base[k] for k in allowed if k in base}
    home = Path(scratch) / "home"
    tmp = Path(scratch) / "tmp"
    for d in (home, tmp):
        d.mkdir(parents=True, exist_ok=True)
    path = [*path_dirs, *[p for p in SYSTEM_PATH if p not in path_dirs]]
    env.update({"PATH": os.pathsep.join(path), "TMPDIR": str(tmp)})
    if "HOME" not in keep:
        env["HOME"] = str(home)
    elif "HOME" in base:
        env["HOME"] = base["HOME"]
    report = {
        "environment": "scrubbed",
        "variables": sorted(env),
        "inherited_dropped": len([k for k in base if env.get(k) != base[k]]),
        "path": path,
        "limits": list(LIMITS),
    }
    return env, report


INHERITED = {
    "environment": "inherited",
    "variables": None,
    "inherited_dropped": 0,
    "path": None,
    "limits": ["the full parent environment is passed to every check"],
}
