#!/usr/bin/env python3
"""Consumer-side run: select the consumer's pinned platform release, provision its toolchains, execute the
consumer's checks and produce verifiable execution evidence, from public pins only (ADR 0021).

Run it from the consumer's CI, in addition to (never instead of) the consumer's own build and security gates:

  python3 tools/consumer_run.py --consumer-dir . --work "$RUNNER_TEMP/dp" --evidence-dir dp-evidence \\
      [--dev-platform-checkout <dir at the pinned revision>] [--allow-unaccepted]

Pins are the consumer's own, committed in its repository and reviewed in its own pull requests:
  dev-platform.toml                 platform version + tree sha256 + profile; the `[infra]` configuration pin
  dev-platform.release-pins.json    the release identity (a subset of releases/<version>/identity.json):
                                    version, source_revision, archive_sha256, tree_digest_pin, verifier_pins
  .dev-platform/infra-profile.json  the vendored infrastructure profile (sha256 equals `[infra] config_digest`)
Nothing private is read: the trusted installer, verifier and policy come from the public platform repository at the
pinned revision and must equal the pinned digests. A provider is never called here (untrusted-safe).

Steps: pins consistent -> trusted tools at the pinned revision -> verified install -> `toolchain provision --pinned
--verify` (twice, identity must be identical) -> doctor -> `check --stage full --result` -> Bazel Rust toolchain proof
(rust-bazel profiles) -> evidence bundle -> independent verification against the consumer's pins.
Exit 0 only when the consumer evidence is `verified`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

DEFAULT_REPO = "https://github.com/syncom-systems/dev-platform"
PINS_FILE = "dev-platform.release-pins.json"
VERIFY_EVIDENCE = Path(__file__).resolve().parent / "verify_consumer_evidence.py"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REV = re.compile(r"^[0-9a-f]{40}$")


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kw)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_pins(consumer: Path) -> tuple[dict, dict, list[str]]:
    """(release pins, parsed dev-platform.toml, problems). The two files must agree."""
    problems: list[str] = []
    try:
        cfg = tomllib.loads((consumer / "dev-platform.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        return {}, {}, [f"dev-platform.toml: {e}"]
    try:
        pins = json.loads((consumer / PINS_FILE).read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {}, cfg, [f"{PINS_FILE}: {e}"]
    vp = pins.get("verifier_pins") or {}
    need = {
        "version": isinstance(pins.get("version"), str),
        "source_revision": bool(_REV.match(str(pins.get("source_revision")))),
        "archive_sha256": bool(_SHA.match(str(pins.get("archive_sha256")))),
        "tree_digest_pin": bool(_SHA.match(str(pins.get("tree_digest_pin")))),
        "verify_release.py_sha256": bool(_SHA.match(str(vp.get("verify_release.py_sha256")))),
        "trust_policy_sha256": bool(_SHA.match(str(vp.get("trust_policy_sha256")))),
        "install_release.py_sha256": bool(_SHA.match(str(vp.get("install_release.py_sha256")))),
    }
    problems += [f"{PINS_FILE}: {k} missing or malformed" for k, ok in need.items() if not ok]
    plat = cfg.get("platform") or {}
    if plat.get("self_hosted"):
        problems.append("dev-platform.toml is self-hosted: not a consumer configuration")
    if pins.get("version") != plat.get("version"):
        problems.append(
            f"{PINS_FILE} version {pins.get('version')} != dev-platform.toml {plat.get('version')}"
        )
    if pins.get("tree_digest_pin") != plat.get("sha256"):
        problems.append(f"{PINS_FILE} tree_digest_pin != dev-platform.toml platform.sha256")
    return pins, cfg, problems


def event_trust(env=os.environ) -> str:
    """The platform's own derivation (never a consumer or provider claim); unknown context is untrusted."""
    ev = env.get("GITHUB_EVENT_NAME")
    if not ev:
        return "untrusted"
    head = base = env.get("GITHUB_REPOSITORY")
    try:
        payload = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
        pr = payload.get("pull_request") or {}
        head = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or head
        base = ((pr.get("base") or {}).get("repo") or {}).get("full_name") or base
    except (KeyError, OSError, json.JSONDecodeError):
        pass
    argv = [sys.executable, "-m", "dev_platform", "infra", "event-trust", "--event", ev,
            "--head-repo", head or "", "--base-repo", base or ""]  # fmt: skip
    if env.get("GITHUB_REF_PROTECTED") == "true":
        argv.append("--protected-ref")
    r = run(argv, env=env)
    try:
        return json.loads(r.stdout)["event_trust"] if r.returncode == 0 else "untrusted"
    except (json.JSONDecodeError, KeyError):
        return "untrusted"


def trusted_tools(pins: dict, work: Path, repo_url: str, checkout: Path | None) -> tuple[Path | None, str]:
    """Write verify_release.py, policy.json, install_release.py from the pinned revision; they must equal the pins."""
    rev = pins["source_revision"]
    trust = work / "trust"
    (trust / "tools").mkdir(parents=True, exist_ok=True)
    ref = "HEAD"
    if checkout is None:
        src = work / "dev-platform-src"
        run(["git", "init", "-q", str(src)])
        r = run(["git", "-C", str(src), "fetch", "-q", "--depth", "1", repo_url, rev])
        if r.returncode:
            return None, "cannot fetch the pinned revision from the platform repository"
        checkout, ref = src, "FETCH_HEAD"
    head = run(["git", "-C", str(checkout), "rev-parse", ref]).stdout.strip()
    if head != rev:
        return None, "the platform checkout is not at the pinned revision"
    wants = (
        ("tools/verify_release.py", trust / "tools" / "verify_release.py", "verify_release.py_sha256"),
        ("trust/policy.json", trust / "policy.json", "trust_policy_sha256"),
        ("tools/install_release.py", trust / "tools" / "install_release.py", "install_release.py_sha256"),
    )
    for rel, dest, pin_name in wants:
        r = run(["git", "-C", str(checkout), "show", f"{ref}:{rel}"])
        if r.returncode:
            return None, f"cannot read {rel} at the pinned revision"
        dest.write_text(r.stdout)
        if sha(dest) != pins["verifier_pins"][pin_name]:
            return None, f"{rel} at the pinned revision does not equal its pinned digest"
    return trust, ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--consumer-dir", type=Path, default=Path("."))
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--dev-platform-repo", default=DEFAULT_REPO)
    ap.add_argument(
        "--dev-platform-checkout", type=Path, help="existing checkout of the platform at the pinned revision"
    )
    ap.add_argument(
        "--allow-unaccepted", action="store_true", help="use a release that is verified but not accepted"
    )
    ap.add_argument("--infra-profile", type=Path, help="default: .dev-platform/infra-profile.json if present")
    ap.add_argument(
        "--event-trust", choices=["trusted", "untrusted"], help="default: derived from the CI event"
    )
    a = ap.parse_args(argv)
    cd, work, ev = a.consumer_dir.resolve(), a.work.resolve(), a.evidence_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    ev.mkdir(parents=True, exist_ok=True)
    rec: dict = {"schema": "dev-platform.consumer-run/v1", "steps": {}}

    def finish(code: int) -> int:
        (ev / "consumer-run.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
        print(json.dumps(rec["steps"], indent=2, sort_keys=True))
        return code

    pins, cfg, problems = read_pins(cd)
    rec["steps"]["pins_consistent"] = not problems
    if problems:
        rec["steps"]["problems"] = problems
        return finish(1)
    ver = pins["version"]
    trust, why = trusted_tools(pins, work, a.dev_platform_repo, a.dev_platform_checkout)
    rec["steps"]["trusted_tools"] = trust is not None
    if trust is None:
        rec["steps"]["problems"] = [why]
        return finish(1)
    vp = pins["verifier_pins"]
    inst = [sys.executable, str(trust / "tools" / "install_release.py"), "--version", ver,
            "--store", str(work / "store"), "--verifier-sha256", vp["verify_release.py_sha256"],
            "--policy", str(trust / "policy.json"), "--policy-sha256", vp["trust_policy_sha256"],
            "--archive-sha256", pins["archive_sha256"], "--tree-sha256", pins["tree_digest_pin"],
            "--source-revision", pins["source_revision"]]  # fmt: skip
    if a.allow_unaccepted:
        inst.append("--allow-unaccepted")
    r = run(inst)
    rec["steps"]["installed"] = r.returncode == 0
    if r.returncode:
        rec["steps"]["problems"] = [(r.stdout + r.stderr).strip()[-400:]]
        return finish(1)
    env = {**os.environ, "DEV_PLATFORM_STORE": str(work / "store"),
           "PYTHONPATH": str(work / "store" / ver / "src")}  # fmt: skip
    dp = [sys.executable, "-m", "dev_platform"]
    prov = [*dp, "toolchain", "provision", "--pinned", "--verify", "--project", str(cd),
            "--profile", cfg["platform"]["profile"], "--dest"]  # fmt: skip
    verifications = []
    for name in ("devenv", "devenv2"):
        r = run([*prov, str(work / name)], env=env)
        try:
            verifications.append(json.loads(r.stdout.strip().splitlines()[0]).get("verification") or {})
        except (IndexError, json.JSONDecodeError):
            verifications.append({})
        rec["steps"][f"provision_{name}_exit"] = r.returncode
    rec["steps"]["toolchain_verification"] = verifications[0]
    rec["steps"]["provision_deterministic"] = bool(verifications[0].get("identity_digest")) and (
        verifications[0] == verifications[1]
    )
    dest = work / "devenv"
    dirs = [str(dest / "bin")] + [str(p / "bin") for p in sorted(dest.iterdir()) if (p / "bin").is_dir()]
    env["PATH"] = os.pathsep.join([*dirs, env["PATH"]])
    trust_level = a.event_trust or event_trust(env)
    rec["steps"]["event_trust"] = trust_level
    infra_file = a.infra_profile or cd / ".dev-platform" / "infra-profile.json"
    infra_args = ["--infra-profile", str(infra_file)] if infra_file.is_file() else []
    rec["steps"]["doctor_exit"] = run([*dp, "doctor", "--project", str(cd), *infra_args], env=env).returncode
    result = ev / "result.json"
    result.unlink(missing_ok=True)
    r = run([*dp, "check", "--project", str(cd), "--stage", "full", "--event-trust", trust_level,
             "--result", str(result), *infra_args], env=env)  # fmt: skip
    rec["steps"]["check_exit"] = r.returncode
    rec["steps"]["check_tail"] = (r.stdout + r.stderr).strip().splitlines()[-12:]
    if not result.is_file():
        rec["steps"]["problems"] = ["no result record produced"]
        return finish(1)
    proof = None
    if cfg["platform"]["profile"].startswith("rust-bazel"):
        proof = ev / "bazel-rust-proof.json"
        run([*dp, "toolchain", "prove-bazel-rust", "--project", str(cd), "--out", str(proof)], env=env)
        rec["steps"]["bazel_rust_proof"] = proof.is_file() and json.loads(proof.read_text()).get("ok") is True
    (ev / "dev-platform.toml").write_text((cd / "dev-platform.toml").read_text())
    (ev / PINS_FILE).write_text((cd / PINS_FILE).read_text())
    vargs = [sys.executable, "-I", str(VERIFY_EVIDENCE), "--result", str(result),
             "--config", str(ev / "dev-platform.toml"), "--out", str(ev / "verification.json")]  # fmt: skip
    if proof and proof.is_file():
        vargs += ["--bazel-proof", str(proof), "--require-bazel-proof"]
    run(vargs)
    v = json.loads((ev / "verification.json").read_text()) if (ev / "verification.json").is_file() else {}
    rec["steps"]["evidence_verdict"] = v.get("verdict", "no-record")
    return finish(0 if v.get("verdict") == "verified" and r.returncode == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
