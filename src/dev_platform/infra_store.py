"""Local store of exactly selected configuration releases and the current authorization policy (ADR 0023).

The store has the configuration-repository layout (`infra_release`), so `dev-platform infra resolve --root
<store>` resolves from it. A release enters only by exact selection (version AND release-tree digest, the
consumer's pin), only when the source's index names that digest and the received bytes have it. It is
written once, read-only, and never replaced: an entry with other bytes is an integrity failure left in place
for inspection. Releases coexist; nothing here picks "the newest", and a newer CLI never changes what is
stored.

The policy is mutable and refreshed from the source on every fetch or sync, forward only: a lower revision
of the same policy, a different policy, or other content under a revision already seen is refused.

Sources are named explicitly, never defaulted: a local directory (`import`), or one commit of a GitHub
repository read with the caller's own identity through `gh` (`fetch`, `sync`). No credential is stored.
Without access nothing is fetched and the store is unchanged; what is stored keeps working offline.

Location: `--store`, else `<data root>/infra` (`DEV_PLATFORM_HOME`, in CI a job-local
`$RUNNER_TEMP/dev-platform`, else `${XDG_DATA_HOME:-~/.local/share}/dev-platform`).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from dev_platform import infra_authz
from dev_platform.infra_provider import POLICY
from dev_platform.infra_release import (
    INDEX,
    WIRE_DIGEST_RE,
    ReleaseError,
    canonical,
    check_index,
    digest_of,
    empty_index,
    in_tree_order,
    index_bytes,
    manifest_of,
    read_tree,
    version_key,
)

SOURCE = "authorization/source.json"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_GH_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


@dataclass
class Source:
    """One snapshot of a configuration repository: only the paths the store needs."""

    origin: str
    commit: str | None
    files: dict[str, bytes]
    links: set[str] = field(default_factory=set)  # entries that were symlinks or special files

    def index(self) -> dict:
        try:
            return check_index(json.loads(self.files[INDEX]))
        except KeyError:
            raise ReleaseError("index-invalid", f"{self.origin}: no {INDEX}") from None
        except ValueError as e:
            raise ReleaseError("index-invalid", f"{self.origin}: {e}") from None

    def release(self, version: str) -> dict[str, bytes]:
        pre = f"releases/{version}/"
        if any(p.startswith(pre) or p == pre.rstrip("/") for p in self.links):
            raise ReleaseError("release-tampered", f"{version}: contains a symlink or special file")
        files = {p[len(pre) :]: b for p, b in self.files.items() if p.startswith(pre)}
        if not files:
            raise ReleaseError("release-unreadable", f"{self.origin}: no release directory {version}")
        return in_tree_order(files)

    def policy(self) -> dict:
        if POLICY in self.links or POLICY not in self.files:
            raise ReleaseError("policy-invalid", f"{self.origin}: no regular {POLICY}")
        try:
            return infra_authz.validate(json.loads(self.files[POLICY]))
        except ValueError as e:
            raise ReleaseError("policy-invalid", f"{self.origin}: {e}") from None


def _wanted(rel: str, version: str | None) -> bool:
    return rel in (INDEX, POLICY) or rel.startswith(f"releases/{version}/" if version else "releases/")


def from_directory(path: Path, version: str | None = None) -> Source:
    path = Path(path).absolute()
    if not path.is_dir():
        raise ReleaseError("source-unreadable", f"{path}: not a directory")
    files: dict[str, bytes] = {}
    links: set[str] = set()
    for rel in (INDEX, POLICY):
        p = path / rel
        if p.is_symlink():
            links.add(rel)
        elif p.is_file():
            files[rel] = p.read_bytes()
    top = path / "releases" / version if version else path / "releases"
    if top.is_symlink():
        links.add(top.relative_to(path).as_posix())
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        for n in [*dirnames, *filenames]:
            p = Path(dirpath) / n
            rel = p.relative_to(path).as_posix()
            if p.is_symlink() or (n in filenames and not p.is_file()):
                links.add(rel)
            elif n in filenames and rel != INDEX:
                files[rel] = p.read_bytes()
    commit = None
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30
        )
        commit = out.stdout.strip() if out.returncode == 0 and _SHA.fullmatch(out.stdout.strip()) else None
    except (OSError, subprocess.SubprocessError):
        pass
    return Source(f"directory:{path}", commit, files, links)


def from_tarball(data: bytes, origin: str, commit: str, version: str | None = None) -> Source:
    files: dict[str, bytes] = {}
    links: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            for m in tf:
                parts = m.name.split("/", 1)
                if len(parts) != 2 or not parts[1]:
                    continue
                rel = parts[1].rstrip("/")
                if rel.startswith("/") or ".." in rel.split("/") or not _wanted(rel, version) or m.isdir():
                    continue
                f = tf.extractfile(m) if m.isfile() else None
                if f is None:
                    links.add(rel)
                    continue
                files[rel] = f.read()
    except (tarfile.TarError, OSError, EOFError) as e:
        raise ReleaseError("source-unreadable", f"{origin}: {e}") from None
    return Source(origin, commit, files, links)


def _gh(args: list[str], runner) -> bytes:
    try:
        p = runner(["gh", *args], capture_output=True, timeout=300)
    except FileNotFoundError:
        raise ReleaseError("access-unavailable", "gh is not installed") from None
    except subprocess.TimeoutExpired:
        raise ReleaseError("access-unavailable", "gh timed out") from None
    if p.returncode != 0:
        first = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()[:1]
        raise ReleaseError(
            "access-denied",
            "GitHub refused or could not be reached: "
            + (first[0] if first else f"gh exited {p.returncode}")
            + " (check `gh auth status`)",
        )
    return p.stdout


def _check_source(repo: str, ref: str) -> None:
    if not _GH_REPO.fullmatch(repo or ""):
        raise ReleaseError("usage", f"source {repo!r}: OWNER/NAME of the configuration repository")
    if not _REF.fullmatch(ref or "") or ".." in ref:
        raise ReleaseError("usage", f"ref {ref!r}: a branch, tag or commit")


def commit_of(repo: str, ref: str, runner=subprocess.run) -> str:
    _check_source(repo, ref)
    commit = (
        _gh(["api", "--method", "GET", f"repos/{repo}/commits/{ref}", "--jq", ".sha"], runner)
        .decode()
        .strip()
    )
    if not _SHA.fullmatch(commit):
        raise ReleaseError("access-denied", f"could not resolve {repo}@{ref}")
    return commit


def from_github(repo: str, ref: str, version: str | None = None, runner=subprocess.run) -> Source:
    commit = commit_of(repo, ref, runner)
    data = _gh(["api", "--method", "GET", f"repos/{repo}/tarball/{commit}"], runner)
    return from_tarball(data, f"github:{repo}@{commit}", commit, version)


def policy_from_github(repo: str, ref: str, runner=subprocess.run) -> Source:
    commit = commit_of(repo, ref, runner)
    raw = _gh(
        [
            "api",
            "--method",
            "GET",
            f"repos/{repo}/contents/{POLICY}?ref={commit}",
            "-H",
            "Accept: application/vnd.github.raw",
        ],
        runner,
    )
    return Source(f"github:{repo}@{commit}", commit, {POLICY: raw})


@contextmanager
def _locked(store: Path):
    import fcntl

    store.mkdir(parents=True, exist_ok=True)
    with open(store / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _remove(path: Path) -> None:
    """Remove a read-only tree this process created (never a store entry)."""
    if not path.exists():
        return
    for dirpath, _, _ in os.walk(path):
        os.chmod(dirpath, 0o700)
    shutil.rmtree(path, ignore_errors=True)


def store_index(store: Path) -> dict:
    p = store / INDEX
    if not p.exists():
        return empty_index()
    try:
        return check_index(json.loads(p.read_bytes()))
    except (ValueError, ReleaseError) as e:
        raise ReleaseError("store-corrupt", f"{p}: {e}") from None


def selection(version: object, digest: object) -> tuple[str, str]:
    """(version, bare hex) from a consumer's exact selection."""
    version_key(version)
    if not isinstance(digest, str) or not WIRE_DIGEST_RE.fullmatch(digest):
        raise ReleaseError(
            "selection-invalid", "digest must be 'sha256:' + 64 lowercase hex (the consumer's pin)"
        )
    return str(version), digest[7:]


def install_release(store: Path, src: Source, version: str, digest: str) -> str:
    """Put exactly the selected release into the store: "installed", or "present" if it already is."""
    version, hexd = selection(version, digest)
    entry = next((r for r in src.index()["releases"] if r["version"] == version), None)
    if entry is None:
        raise ReleaseError("version-unknown", f"{src.origin}: no release {version} in the index")
    if entry["digest"] != hexd:
        raise ReleaseError("digest-mismatch", f"{version}: the selected digest is not the indexed one")
    files = src.release(version)
    if digest_of(files) != hexd:
        raise ReleaseError(
            "release-tampered", f"{version}: received content does not have the indexed digest"
        )
    # a format this platform resolves for that contract, or refused
    manifest_of(files, version, entry["contract"])
    dest = store / "releases" / version
    with _locked(store):
        idx = store_index(store)
        mine = next((r for r in idx["releases"] if r["version"] == version), None)
        if mine is not None and mine != entry:
            raise ReleaseError("store-corrupt", f"{version}: the store index names another identity")
        if dest.exists() or dest.is_symlink():
            try:
                ok = not dest.is_symlink() and digest_of(read_tree(dest)) == hexd
            except (OSError, ReleaseError):
                ok = False
            if not ok:
                raise ReleaseError("store-corrupt", f"{dest}: not the selected release; left in place")
            action = "present"
        else:
            (store / "releases").mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=store / "releases"))
            try:
                for rel, data in files.items():
                    p = tmp / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                for d in sorted({(tmp / rel).parent for rel in files} - {tmp}, key=lambda p: -len(p.parts)):
                    os.chmod(d, 0o555)  # noqa: S103 (read-only; store entries hold no secrets)
                if digest_of(read_tree(tmp)) != hexd:  # what is stored is what was verified
                    raise ReleaseError("release-tampered", f"{version}: written content differs")
                # The top directory stays writable until it is in place: macOS refuses to rename a read-only
                # directory.
                os.rename(tmp, dest)
            except BaseException:
                _remove(tmp)
                raise
            os.chmod(dest, 0o555)  # noqa: S103 (read-only; store entries hold no secrets)
            action = "installed"
        if mine is None:
            idx["releases"].append(dict(entry))
            idx["releases"].sort(key=lambda r: version_key(r["version"]))
            _atomic_write(store / INDEX, index_bytes(idx))
    return action


def stored_policy(store: Path) -> dict | None:
    p = store / POLICY
    if not p.exists():
        return None
    try:
        return infra_authz.validate(json.loads(p.read_bytes()))
    except (ValueError, OSError) as e:
        raise ReleaseError("store-corrupt", f"{p}: {e}") from None


def install_policy(store: Path, src: Source, now: float | None = None) -> str:
    """Store the source's policy unless it is older: "updated" or "unchanged"."""
    pol = src.policy()
    with _locked(store):
        old = stored_policy(store)
        action = "updated"
        if old is not None:
            if old["policy_id"] != pol["policy_id"]:
                raise ReleaseError(
                    "policy-mismatch",
                    f"stored policy {old['policy_id']!r}, source {pol['policy_id']!r}; refusing to switch",
                )
            if pol["revision"] < old["revision"]:
                raise ReleaseError(
                    "policy-rollback",
                    f"source revision {pol['revision']} is older than stored {old['revision']}",
                )
            if pol["revision"] == old["revision"]:
                if infra_authz.policy_digest(pol) != infra_authz.policy_digest(old):
                    raise ReleaseError(
                        "policy-conflict", f"revision {pol['revision']} has other content at the source"
                    )
                action = "unchanged"
        _atomic_write(store / POLICY, canonical(pol))
        if not (store / INDEX).exists():
            _atomic_write(store / INDEX, index_bytes(empty_index()))
        _atomic_write(
            store / SOURCE,
            canonical(
                {
                    "schema": "dev-platform.infra-policy-source/v1",
                    "origin": src.origin,
                    "commit": src.commit,
                    "policy": infra_authz.identity(pol),
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                }
            ),
        )
    return action


def policy_source(store: Path) -> dict | None:
    try:
        return json.loads((store / SOURCE).read_bytes())
    except (OSError, ValueError):
        return None


def verify(store: Path) -> list[dict]:
    """Every stored release against its stored identity: ok | tampered | missing | unindexed."""
    out: list[dict] = []
    if not (store / "releases").is_dir():
        return out
    listed = {r["version"]: r for r in store_index(store)["releases"]}
    for v, r in sorted(listed.items(), key=lambda kv: version_key(kv[0])):
        d = store / "releases" / v
        try:
            status = "ok" if digest_of(read_tree(d)) == r["digest"] else "tampered"
        except ReleaseError as e:
            status = "missing" if e.code == "release-unreadable" and not d.exists() else "tampered"
        except OSError:
            status = "tampered"
        out.append(
            {"version": v, "digest": "sha256:" + r["digest"], "contract": r["contract"], "status": status}
        )
    for d in sorted((store / "releases").iterdir()):
        if d.is_dir() and not d.name.startswith(".") and d.name not in listed:
            out.append({"version": d.name, "digest": None, "contract": None, "status": "unindexed"})
    return out


def location(
    env=os.environ, store: Path | None = None, project: Path | None = None, *, home: Path | None = None
) -> tuple[Path, str]:
    """(store, chosen by): `--store`, else <data root>/infra. The one calculation for `install` and every
    `infra` command; the platform release store (`--store` of `setup`) is a different location and never
    moves this one. A location inside the project or its Git metadata is refused (ADR 0027)."""
    from dev_platform import pathguard
    from dev_platform.locations import data_root

    if store:
        path, why = Path(store).absolute(), "--store"
    else:
        root, _scope, why = data_root(env, home)
        path = (root / "infra").absolute()
    pathguard.guard(path, f"infrastructure store (from {why})", project)
    return path, why


__all__ = [
    "Source",
    "from_directory",
    "from_github",
    "install_policy",
    "install_release",
    "location",
    "policy_from_github",
    "stored_policy",
    "verify",
]
