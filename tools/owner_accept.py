#!/usr/bin/env python3
"""Owner-only: accept a platform release with two signed commits (docs/owner-acceptance-0.2.1.md, Part B).

Run it yourself in a terminal: `python3 tools/owner_accept.py --version 0.2.1`.
It refuses to run without an interactive terminal and needs you to type a confirmation phrase, so an agent
cannot run it for you. It uses your own git signing key; it never creates keys and never reads secrets.
Nothing is written until you confirm; the release and releases/<version>/ are not modified.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*cmd, check=True):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default="0.2.1")
    ap.add_argument("--no-push", action="store_true", help="commit locally only")
    args = ap.parse_args()
    v = args.version

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("refusing: this must be run by the owner in an interactive terminal")

    ident = json.loads((ROOT / f"releases/{v}/identity.json").read_text())
    template = json.loads((ROOT / f"releases/{v}/authorization.template.json").read_text())
    rev, digest = ident["source_revision"], ident["archive_sha256"]
    policy_pin = ident["verifier_pins"]["trust_policy_sha256"]

    if run("git", "status", "--porcelain"):
        sys.exit("refusing: working tree is not clean")
    if run("git", "rev-parse", "--abbrev-ref", "HEAD") != "main":
        sys.exit("refusing: not on main")
    run("git", "fetch", "origin", "main")
    if run("git", "rev-parse", "HEAD") != run("git", "rev-parse", "origin/main"):
        sys.exit("refusing: main is not identical to origin/main (pull or push first)")
    if not run("git", "config", "--get", "user.signingkey", check=False):
        sys.exit(
            "refusing: no git signing key configured. Create one and register it at "
            "github.com/settings/keys as a *signing* key, then:\n"
            "  git config --global user.signingkey <key or path.pub>\n"
            "  git config --global gpg.format ssh   # if it is an SSH key"
        )
    login = run("gh", "api", "user", "-q", ".login")

    policy_text = run("git", "show", f"{rev}:trust/policy.json")
    if hashlib.sha256((policy_text + "\n").encode()).hexdigest() != policy_pin and \
            hashlib.sha256(policy_text.encode()).hexdigest() != policy_pin:
        sys.exit("refusing: policy at the release's source revision does not match the pinned digest")
    policy = json.loads(policy_text)
    if policy["authorization"]["approvers"]:
        sys.exit("refusing: release policy already lists approvers; expected an empty list")
    policy["authorization"]["approvers"] = [{
        "id": "owner", "provider": "github-signed-commit", "login": login,
        "roles": ["owner"], "may_approve": ["platform-release"], "may_confer": ["platform-baseline"],
    }]

    name = f"platform-{v}"
    rec_path = f"authorizations/{name}.json"
    pol_path = f"releases/{v}-acceptance/trust-policy.json"
    record = {k: val for k, val in template.items() if k != "_comment"}
    record["id"] = f"{name}-owner"
    record["decision"] = "approved"
    record["decided_by"] = {"id": "owner", "role": "owner", "identity_assertion": {
        "provider": "github-signed-commit", "login": login, "path": rec_path}}
    record["decided_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record.pop("validity", None)

    print(f"\nYou ({login}) are about to authorize:\n"
          f"  dev-platform {v}, archive sha256 {digest}\n"
          f"  scope: {record['scope']['confers']}\n"
          f"  basis: {record['basis']['reference']} (read it first)\n"
          f"Two signed commits will be pushed to main: {pol_path} (you as approver), then {rec_path}.\n"
          "This is permanent; changing your mind later is a new signed 'revoked' record.\n")
    phrase = f"I authorize {v} {digest[:12]}"
    if input(f'Type exactly "{phrase}" to continue: ').strip() != phrase:
        sys.exit("not confirmed; nothing written")

    (ROOT / pol_path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / pol_path).write_text(json.dumps(policy, indent=2) + "\n")
    (ROOT / rec_path).parent.mkdir(exist_ok=True)
    (ROOT / rec_path).write_text(json.dumps(record, indent=2) + "\n")

    shas = []
    for path, msg in ((pol_path, f"Owner approver policy for v{v} acceptance"),
                      (rec_path, f"Authorize dev-platform {v} (platform-baseline)")):
        run("git", "add", path)
        run("git", "commit", "-S", "-m", msg)
        shas.append(run("git", "rev-parse", "HEAD"))
    if args.no_push:
        print("committed locally; push with: git push origin main")
        return
    run("git", "push", "origin", "main")

    repo = run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    ok = True
    for sha in shas:
        ver = run("gh", "api", f"repos/{repo}/commits/{sha}", "-q", ".commit.verification.reason")
        print(f"{sha[:10]} GitHub verification: {ver}")
        ok &= ver == "valid"
    print(f"\npolicy pin (record this digest outside the repo): {sha256(ROOT / pol_path)}")
    if not ok:
        print("A commit is not 'valid' on GitHub: the key or email is not registered. The record will not "
              "authenticate. Fix the key/email, then supersede with a new signed commit; do not edit the record.")
        sys.exit(1)
    print("Done. Tell the agent to run Part C (verification) with that policy pin.")


if __name__ == "__main__":
    main()
