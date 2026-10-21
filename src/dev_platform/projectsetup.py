"""`dev-platform setup`: make a consumer project ready on this machine from the project's own committed pins.

It composes the existing mechanisms; it is not a second release-management system (ADR 0022):
  1. find the project (`dev-platform.toml` and `dev-platform.release-pins.json`, from the working directory
     upwards) and require the two files to agree;
  2. the pinned platform release. If the store holds that version, its tree digest must equal the pin (any
     other tree is refused and left untouched) and the trusted installer's verification record must be beside
     it. Otherwise the trusted installer, verifier and policy are taken from the public platform repository at
     the pinned revision, must equal the pinned digests, and `install_release.py` verifies provenance, SBOM
     and build-environment attestations before anything is extracted (ADR 0014). Admitting a
     verified-unaccepted or pre-release version is the consumer's decision (`--allow-unaccepted`,
     `--allow-prerelease`);
  3. the pinned release itself, run from a verified private snapshot exactly as the launcher runs it,
     verifies the provisioned toolchain profile, or provisions it (`toolchain provision --pinned --verify`);
  4. the pinned release's `doctor` checks the environment.
The project's files are only read. Setup never writes or changes a pin, so it cannot upgrade a project, and
the CLI that runs it is only the launcher: its own version never selects the project's release.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from dev_platform import __version__
from dev_platform.config import CONFIG_FILENAME, load
from dev_platform.digest import tree_digest
from dev_platform.errors import (
    EXIT_OK,
    EXIT_PLATFORM,
    EXIT_UNSATISFIED,
    EXIT_USAGE,
    DevPlatformError,
)
from dev_platform.locations import STORE_ENV, Locations
from dev_platform.provision import platform_key, tool_dirs
from dev_platform.resolve import OVERRIDE_ENV, PACKAGE_ROOT, PYTHON_ENV, REEXEC_ENV, reexec_env, resolve
from dev_platform.toolchain import PYTHON_TOKEN

PINS_FILE = "dev-platform.release-pins.json"
DEFAULT_REPO = "https://github.com/syncom-systems/dev-platform"
MIN_VERSION = (0, 8, 0)  # the first release with `toolchain provision --pinned --verify`
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN")  # for the installer's `gh attestation verify` only
PINNED_TOOLS = (
    ("tools/verify_release.py", "tools/verify_release.py", "verify_release.py_sha256"),
    ("trust/policy.json", "policy.json", "trust_policy_sha256"),
    ("tools/install_release.py", "tools/install_release.py", "install_release.py_sha256"),
)
ADMISSION = {"verified-unaccepted": "--allow-unaccepted", "pre-release": "--allow-prerelease"}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REV = re.compile(r"^[0-9a-f]{40}$")
_VER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.]+)?$")

Run = Callable[..., subprocess.CompletedProcess]


class Refused(DevPlatformError):
    def __init__(self, msg: str, code: int = EXIT_UNSATISFIED):
        super().__init__(msg)
        self.exit_code = code


def run_process(argv, *, env=None, cwd=None, text=True) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=text, check=False)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tail(r: subprocess.CompletedProcess, n: int = 400) -> str:
    return ((r.stdout or "") + (r.stderr or "")).strip()[-n:]


def find_project(start: Path, explicit: bool) -> Path:
    """The directory holding dev-platform.toml: `start` when given explicitly, else the nearest ancestor."""
    start = start.resolve()
    for d in [start] if explicit else [start, *start.parents]:
        if (d / CONFIG_FILENAME).is_file():
            return d
    where = start if explicit else f"{start} or any parent directory"
    raise Refused(f"no {CONFIG_FILENAME} in {where}", EXIT_USAGE)


def read_pins(root: Path):
    """(Config, release pins). The two files must agree on the version and the tree digest."""
    cfg = load(root)
    if cfg.platform.self_hosted:
        raise Refused(
            f"{root / CONFIG_FILENAME} is self-hosted (the platform repository): not a consumer", EXIT_USAGE
        )
    try:
        pins = json.loads((root / PINS_FILE).read_text())
    except FileNotFoundError:
        raise Refused(
            f"no {PINS_FILE} beside {CONFIG_FILENAME}: copy the release identity from the platform's "
            "releases/<version>/identity.json (version, source_revision, archive_sha256, tree_digest_pin, "
            "verifier_pins) and commit it",
            EXIT_USAGE,
        ) from None
    except (OSError, json.JSONDecodeError) as e:
        raise Refused(f"{PINS_FILE}: {e}", EXIT_USAGE) from None
    vp = pins.get("verifier_pins") if isinstance(pins.get("verifier_pins"), dict) else {}
    need = {
        "version": isinstance(pins.get("version"), str) and bool(_VER.match(pins["version"])),
        "source_revision": bool(_REV.match(str(pins.get("source_revision")))),
        "archive_sha256": bool(_SHA.match(str(pins.get("archive_sha256")))),
        "tree_digest_pin": bool(_SHA.match(str(pins.get("tree_digest_pin")))),
        **{f"verifier_pins.{name}": bool(_SHA.match(str(vp.get(name)))) for _, _, name in PINNED_TOOLS},
    }
    problems = [f"{PINS_FILE}: {k} missing or malformed" for k, ok in need.items() if not ok]
    if pins.get("version") != cfg.platform.version:
        problems.append(
            f"{PINS_FILE} version {pins.get('version')} != {CONFIG_FILENAME} {cfg.platform.version}"
        )
    if pins.get("tree_digest_pin") != cfg.platform.sha256:
        problems.append(f"{PINS_FILE} tree_digest_pin != {CONFIG_FILENAME} platform.sha256")
    if problems:
        raise Refused("; ".join(problems), EXIT_USAGE)
    m = _VER.match(pins["version"])
    if tuple(int(x) for x in m.groups()[:3]) < MIN_VERSION:
        raise Refused(
            f"the pinned release {pins['version']} predates `toolchain provision --pinned --verify` "
            f"({'.'.join(map(str, MIN_VERSION))}); install it with tools/install_release.py "
            "(docs/consumer-quickstart.md)",
            EXIT_USAGE,
        )
    return cfg, pins


def recorded_state(record_file: Path, pins: dict) -> str | None:
    """The admitted state the trusted installer recorded for exactly this release, or None."""
    try:
        rec = json.loads(record_file.read_text())
        subject = rec["subject"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if (subject.get("version"), subject.get("tree_digest"), subject.get("archive_sha256")) != (
        pins["version"],
        pins["tree_digest_pin"],
        pins["archive_sha256"],
    ):
        return None
    return (rec.get("installation") or {}).get("admitted_state") or (rec.get("acceptance") or {}).get("state")


def admit(state: str, *, allow_unaccepted: bool, allow_prerelease: bool) -> None:
    allowed = {"accepted": True, "verified-unaccepted": allow_unaccepted, "pre-release": allow_prerelease}
    if not allowed.get(state, False):
        flag = ADMISSION.get(state)
        raise Refused(
            f"the pinned release is {state}"
            + (f"; using it is the consumer's decision: pass {flag}" if flag else "; it is not admitted"),
        )


def pinned_tools(pins: dict, cache: Path, out: Path, repo_url: str, run: Run, env: dict) -> Path:
    """Write the trusted installer, verifier and policy at the pinned revision into `out`; each must equal its
    pin.
    The git objects are cached, but never trusted: the bytes are re-checked against the pins on every use."""
    git = cache / "platform.git"
    if not (git / "HEAD").is_file():
        git.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q", "--bare", str(git)], env=env)
    rev = pins["source_revision"]
    g = ["git", "--git-dir", str(git)]
    if run([*g, "cat-file", "-e", f"{rev}^{{commit}}"], env=env).returncode:
        r = run([*g, "fetch", "-q", "--depth", "1", repo_url, rev], env=env)
        if r.returncode:
            raise Refused(f"cannot fetch the pinned platform revision {rev} from {repo_url}: {tail(r, 200)}")
    for rel, dest, pin_name in PINNED_TOOLS:
        r = run([*g, "show", f"{rev}:{rel}"], env=env, text=False)
        if r.returncode:
            raise Refused(f"cannot read {rel} at the pinned revision {rev}")
        if sha256(r.stdout) != pins["verifier_pins"][pin_name]:
            raise Refused(
                f"{rel} at the pinned revision {rev} does not equal {PINS_FILE} verifier_pins.{pin_name}: "
                "the release pins and the platform repository disagree; nothing was installed",
                EXIT_PLATFORM,
            )
        target = out / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(r.stdout)
    return out


def ensure_release(pins, loc: Locations, *, opts: dict, run: Run, env: dict, creds: dict) -> dict:
    ver, pin = pins["version"], pins["tree_digest_pin"]
    dest = loc.store / ver
    record_file = loc.store / ".records" / f"{ver}.verification.json"
    out = {"version": ver, "path": str(dest), "record": str(record_file)}
    existed = dest.exists()
    if existed:
        try:
            actual = tree_digest(dest)
        except (OSError, ValueError) as e:
            raise Refused(f"cannot digest {dest}: {e}", EXIT_PLATFORM) from None
        if actual != pin:
            raise Refused(
                f"{dest} holds tree {actual}, not the pinned {pin} (corrupted, or a different release under "
                f"this version). It was not modified: inspect it, remove it yourself (chmod -R u+w {dest} && "
                f"rm -rf {dest}) and run setup again",
                EXIT_PLATFORM,
            )
        state = recorded_state(record_file, pins)
        if state and not opts["reverify"]:
            admit(state, allow_unaccepted=opts["allow_unaccepted"], allow_prerelease=opts["allow_prerelease"])
            return {
                **out,
                "action": "present",
                "state": state,
                "verified": "by the pinned trusted installer at installation; tree digest re-checked now",
            }
        if not state and not opts["reverify"]:
            raise Refused(
                f"{dest} equals the pin but has no verification record from the trusted installer "
                f"({record_file}); run setup with --reverify to verify the release now"
            )
    if not shutil.which("gh", path=env.get("PATH")):
        raise Refused(
            "the trusted installer verifies attestations with the GitHub CLI: install gh (brew install gh) "
            "and authenticate it (gh auth login)"
        )
    loc.cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pinned-", dir=loc.cache) as tmp:
        tools = pinned_tools(pins, loc.cache, Path(tmp), opts["repo_url"], run, env)
        vp = pins["verifier_pins"]
        argv = [
            sys.executable,
            "-I",
            str(tools / "tools" / "install_release.py"),
            "--version",
            ver,
            "--store",
            str(loc.store),
            "--verifier-sha256",
            vp["verify_release.py_sha256"],
            "--policy",
            str(tools / "policy.json"),
            "--policy-sha256",
            vp["trust_policy_sha256"],
            "--archive-sha256",
            pins["archive_sha256"],
            "--tree-sha256",
            pin,
            "--source-revision",
            pins["source_revision"],
        ]
        argv += [
            flag
            for opt, flag in (
                ("allow_unaccepted", "--allow-unaccepted"),
                ("allow_prerelease", "--allow-prerelease"),
            )
            if opts[opt]
        ]
        r = run(argv, env={**env, **creds})  # the only process that receives the GitHub token
    if r.returncode:
        raise Refused(
            f"the trusted installer refused the pinned release: {tail(r)}",
            EXIT_PLATFORM if r.returncode == EXIT_PLATFORM else EXIT_UNSATISFIED,
        )
    m = re.search(r"^acceptance: (\S+)", r.stdout or "", re.M)
    state = m.group(1) if m else recorded_state(record_file, pins)
    if not dest.is_dir() or tree_digest(dest) != pin:
        raise Refused(
            f"the installer reported success but {dest} does not hold the pinned tree", EXIT_PLATFORM
        )
    return {
        **out,
        "action": "reverified" if existed else "installed",
        "state": state,
        "verified": "now, by the pinned trusted installer (provenance, SBOM and build "
        "environment attestations; archive, revision and tree digest pins)",
    }


def child(*args: str, python: str | None = None) -> list[str]:
    """The pinned release's own CLI (`-P`: the working directory never shadows the snapshot)."""
    return [python or sys.executable, "-P", "-m", "dev_platform", *args]


def interpreter(manifest: dict, profile: str, dest: Path) -> str | None:
    """A profile whose python is the interpreter running the platform (`{python}`) is verified, and then used,
    by running the release on the provisioned python; other profiles run on any supported interpreter."""
    tool = manifest["profiles"][profile]["tools"].get("python") or {}
    running = tool.get("executable") == PYTHON_TOKEN or PYTHON_TOKEN in (tool.get("probe") or {}).get(
        "argv", []
    )
    exe = dest / "python" / "bin" / "python3"
    return str(exe) if running and exe.is_file() else None


def with_path(env: dict, dest: Path) -> dict:
    dirs = tool_dirs(dest) if dest.is_dir() else []
    return {**env, "PATH": os.pathsep.join([*dirs, env.get("PATH", "")])}


def first_json(text: str) -> dict:
    with contextlib.suppress(json.JSONDecodeError, IndexError):
        return json.loads(text)
    with contextlib.suppress(json.JSONDecodeError, IndexError):
        return json.loads(text.strip().splitlines()[0])
    return {}


def unsupported_tools(manifest: dict, profile: str, key: str) -> list[str]:
    """The profile's provisioned tools (those with pinned sources) that have no source for host `key`.
    Releases up to 0.10.0 skip them when provisioning, so an unsupported host would only fail verification
    later, without saying why."""
    tools = manifest["profiles"][profile]["tools"]
    return sorted(n for n, t in tools.items() if t.get("source") and key not in t["source"])


def ensure_toolchain(res, profile: str, project: Path, loc: Locations, cenv: dict, run: Run) -> dict:
    """Verify the profile's directory with the pinned release; provision it (bytes only) and verify again if
    that fails. Verification (`toolchain verify --require-certifiable`: closure identity against the release's
    manifest) is the authority; a directory is reused only when it passes."""
    manifest = res.release["toolchains"]
    if profile not in manifest["profiles"]:
        raise Refused(
            f"profile {profile!r} is not in release {res.version} (has {sorted(manifest['profiles'])})",
            EXIT_USAGE,
        )
    unsourced = unsupported_tools(manifest, profile, platform_key())
    if unsourced:
        sourced = [
            set(t["source"]) for t in manifest["profiles"][profile]["tools"].values() if t.get("source")
        ]
        complete = sorted(set.intersection(*sourced))  # hosts with a source for every tool of the profile
        where = f"it supports {', '.join(complete)}" if complete else "no host has a source for every tool"
        raise Refused(
            f"release {res.version} has no pinned source of {', '.join(unsourced)} (profile {profile!r}) for "
            f"this host ({platform_key()}); {where}: run on a supported host, or pin a release that supports "
            "this one"
        )
    dest = loc.toolchain_dir(res.version, profile)
    out = {"profile": profile, "path": str(dest)}
    mf = Path(res.cleanup) / "toolchains.json"  # the verified snapshot's manifest, private to this run
    mf.write_text(json.dumps(manifest))

    def verify() -> tuple[subprocess.CompletedProcess, dict]:
        argv = ["toolchain", "verify", "--manifest", str(mf), "--profile", profile, "--require-certifiable"]
        r = run(child(*argv, python=interpreter(manifest, profile, dest)), env=with_path(cenv, dest),
                cwd=str(project))  # fmt: skip
        return r, first_json(r.stdout or "")

    def facts(rec: dict) -> dict:
        return {k: rec.get(k) for k in ("conformant", "assurance", "identity_digest")}

    if dest.is_dir():
        r, rec = verify()
        if r.returncode == 0 and rec.get("conformant"):
            return {**out, "action": "reused", **facts(rec), "python": interpreter(manifest, profile, dest)}
    argv = ["toolchain", "provision", "--pinned", "--project", str(project), "--profile", profile,
            "--dest", str(dest)]  # fmt: skip
    r = run(child(*argv), env=cenv, cwd=str(project))
    if r.returncode:
        raise Refused(f"release {res.version} could not provision {profile} in {dest}: {tail(r, 300)}")
    r, rec = verify()
    if r.returncode or not rec.get("conformant"):
        raise Refused(
            f"release {res.version} provisioned {profile} in {dest}, but it is not a conformant, certifiable "
            f"environment ({facts(rec) if rec else tail(r, 300)})"
        )
    return {**out, "action": "provisioned", **facts(rec), "python": interpreter(manifest, profile, dest)}


def doctor(project: Path, dest: Path | None, cenv: dict, run: Run, python: str | None = None) -> dict:
    infra = project / ".dev-platform" / "infra-profile.json"
    extra = ["--infra-profile", str(infra)] if infra.is_file() else []
    argv = child("doctor", "--project", str(project), "--json", *extra, python=python)
    r = run(argv, env=with_path(cenv, dest) if dest else cenv, cwd=str(project))
    findings = first_json(r.stdout or "").get("findings") or []
    return {
        "exit": r.returncode,
        "errors": [f["message"] for f in findings if f.get("level") == "error"],
        "warnings": [f["message"] for f in findings if f.get("level") == "warn"],
    }


@contextlib.contextmanager
def locked(cache: Path):
    """One setup at a time per cache (two shells setting up concurrently must not interleave provisioning)."""
    cache.mkdir(parents=True, exist_ok=True)
    with open(cache / "setup.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def setup(
    project: Path | None,
    loc: Locations,
    *,
    allow_unaccepted: bool = False,
    allow_prerelease: bool = False,
    reverify: bool = False,
    repo_url: str = DEFAULT_REPO,
    dry_run: bool = False,
    env=None,
    run: Run = run_process,
) -> tuple[dict, int]:
    """(setup record, exit status). Every refusal is in the record (`problem`) with its exit status."""
    base = dict(os.environ if env is None else env)
    creds = {k: base.pop(k) for k in TOKEN_VARS if k in base}  # handed to the installer alone
    base.pop(REEXEC_ENV, None)
    base.pop(PYTHON_ENV, None)  # children are given their interpreter explicitly
    base[STORE_ENV] = str(loc.store)
    rec: dict = {
        "cli": {
            "version": __version__,
            "path": str(PACKAGE_ROOT),
            "role": "launcher only: the project's pins select the release",
        },
        "locations": {
            "store": str(loc.store),
            "toolchains": str(loc.toolchains),
            "cache": str(loc.cache),
            "scope": loc.scope,
            "chosen_by": loc.chosen_by,
        },
        "ok": False,
    }
    res = None
    try:
        if base.get(OVERRIDE_ENV):
            raise Refused(
                f"{OVERRIDE_ENV} is set: setup prepares the pinned release only; unset it", EXIT_USAGE
            )
        root = find_project(project or Path.cwd(), explicit=project is not None)
        cfg, pins = read_pins(root)
        profile = cfg.platform.profile
        rec["project"] = {"path": str(root), "files": [CONFIG_FILENAME, PINS_FILE]}
        rec["pinned"] = {
            "version": pins["version"],
            "tree_digest": pins["tree_digest_pin"],
            "archive_sha256": pins["archive_sha256"],
            "source_revision": pins["source_revision"],
            "profile": profile,
        }
        if dry_run:
            dest = loc.store / pins["version"]
            tdir = loc.toolchain_dir(pins["version"], profile) if profile else None
            rec["release"] = {
                "version": pins["version"],
                "path": str(dest),
                "action": "would check" if dest.exists() else "would install",
            }
            rec["toolchain"] = (
                {
                    "profile": profile,
                    "path": str(tdir),
                    "action": "would verify" if tdir.is_dir() else "would provision",
                }
                if profile
                else {"action": "none declared"}
            )
            rec["ok"] = True
            return rec, EXIT_OK
        opts = {
            "allow_unaccepted": allow_unaccepted,
            "allow_prerelease": allow_prerelease,
            "reverify": reverify,
            "repo_url": repo_url,
        }
        with locked(loc.cache):
            rec["release"] = ensure_release(pins, loc, opts=opts, run=run, env=base, creds=creds)
            res = resolve(
                cfg, env=base
            )  # verify-then-execute: a private snapshot whose digest equals the pin
            cenv = reexec_env(res, base)
            dest = None
            if profile:
                rec["toolchain"] = ensure_toolchain(res, profile, root, loc, cenv, run)
                dest = Path(rec["toolchain"]["path"])
            else:
                rec["toolchain"] = {"action": "none declared"}
            python = (rec["toolchain"].get("python") or None) if profile else None
            rec["doctor"] = doctor(root, dest, cenv, run, python)
        rec["env"] = {STORE_ENV: str(loc.store), "PATH": tool_dirs(dest) if dest else []}
        if python:
            rec["env"][PYTHON_ENV] = python  # the launcher runs the release on the verified interpreter
        if rec["doctor"]["exit"]:
            raise Refused(
                f"doctor (release {pins['version']}) reports: {'; '.join(rec['doctor']['errors'])}",
                rec["doctor"]["exit"],
            )
        rec["ok"] = True
        return rec, EXIT_OK
    except Refused as e:
        rec["problem"] = str(e)
        return rec, e.exit_code
    except DevPlatformError as e:  # configuration problems, and the launcher's own integrity refusals
        rec["problem"] = "; ".join(getattr(e, "problems", None) or [str(e)])
        return rec, e.exit_code
    finally:
        if res is not None:
            res.dispose()


def shell_env(rec: dict) -> str:
    env = rec.get("env") or {}
    lines = [f"export {STORE_ENV}={shlex.quote(env.get(STORE_ENV, ''))}"]
    if env.get(PYTHON_ENV):
        lines.append(f"export {PYTHON_ENV}={shlex.quote(env[PYTHON_ENV])}")
    else:
        lines.append(f"unset {PYTHON_ENV}")  # another project's interpreter must not carry over
    if env.get("PATH"):
        lines.append(f'export PATH={shlex.quote(os.pathsep.join(env["PATH"]))}:"$PATH"')
    return "\n".join(lines)


def render(rec: dict) -> str:
    out = [f"cli        dev-platform {rec['cli']['version']} ({rec['cli']['path']}): {rec['cli']['role']}"]
    loc = rec["locations"]
    out.append(
        f"locations  {loc['scope']}: store {loc['store']}; toolchains {loc['toolchains']}; "
        f"cache {loc['cache']}"
    )
    if "project" in rec:
        p = rec["pinned"]
        out.append(f"project    {rec['project']['path']}")
        out.append(
            f"pinned     {p['version']} tree {p['tree_digest']} archive {p['archive_sha256']} "
            f"revision {p['source_revision']} profile {p['profile']}"
        )
    if "release" in rec:
        r = rec["release"]
        state = f"; state {r['state']}" if r.get("state") else ""
        verified = f" (verified {r['verified']})" if r.get("verified") else ""
        out.append(f"release    {r['action']}: {r['path']}{state}{verified}")
    if "toolchain" in rec:
        t = rec["toolchain"]
        facts = (
            (
                f" ({'conformant' if t.get('conformant') else 'NOT conformant'}, {t.get('assurance')}, "
                f"identity {t.get('identity_digest')})"
            )
            if "assurance" in t
            else ""
        )
        out.append(f"toolchain  {t['action']}: {t.get('profile', '')} {t.get('path', '')}{facts}".rstrip())
    if "doctor" in rec:
        d = rec["doctor"]
        out.append(
            f"doctor     exit {d['exit']}"
            + "".join(f"\n  error: {m}" for m in d["errors"])
            + "".join(f"\n  warn: {m}" for m in d["warnings"])
        )
    if rec.get("problem"):
        out.append(f"refused    {rec['problem']}")
    elif rec.get("env"):
        out.append('ready      in this shell: eval "$(dev-platform setup --print-env)", which prints:')
        out += ["  " + ln for ln in shell_env(rec).splitlines()]
    return "\n".join(out)
