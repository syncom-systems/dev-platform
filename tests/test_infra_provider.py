"""The generic provider and the current authorization policy, judged by the engine (ADR 0021, ADR 0023).

Every result is also passed through `infra.evaluate`, the function the engine and `infra check-resolution` use, so the
provider and the engine cannot drift apart. Negative cases are as many as positive ones on purpose.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import unittest

from dev_platform import infra, infra_authz, infra_provider, infra_release
from dev_platform.config import InfraPin
from tests.helpers import ROOT, tmpdir
from tests.infra_fixtures import OWNER, VERSION, config_repo, policy, release_files, request, write_policy


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.digests = config_repo(self.root, versions=(VERSION, "2026.02.1"))
        self.digest = self.digests[VERSION]

    def go(self, **kw):
        kw.setdefault("digest", self.digest)
        return infra_provider.resolve(self.root, request(**kw))

    def judged(self, res, version=VERSION, digest=None, kind=None):
        pin = InfraPin("example-infra", version, digest or self.digest, kind)
        req = infra.request_for(pin, repo=f"{OWNER}/app", event_trust="trusted")
        return infra.evaluate(pin, req, res["result"], res["profile_bytes"])

    def code(self, res):
        return res["evidence"]["reasons"][0]["code"] if res["evidence"]["reasons"] else None


class Resolves(Base):
    def test_resolves_the_exact_selection(self):
        res = self.go()
        self.assertEqual(res["result"]["decision"], "resolved")
        self.assertEqual(res["result"]["resolved"], {"version": VERSION, "digest": self.digest})
        self.assertEqual(self.judged(res).status, "resolved")
        self.assertEqual(self.judged(res, kind="release-tree").status, "resolved")

    def test_records_the_policy_identity(self):
        res = self.go()
        self.assertEqual(res["result"]["authorization_policy"], infra_authz.identity(policy()))
        self.assertIsNone(infra.authorization_facts(res["result"]["authorization_policy"]))

    def test_older_pins_stay_resolvable_side_by_side(self):
        for v, d in self.digests.items():
            self.assertEqual(self.go(version=v, digest=d)["result"]["decision"], "resolved", v)

    def test_legacy_layout_release_resolves(self):
        root = tmpdir(self)
        hexd = infra_release.build(root, VERSION, release_files())
        # Rewrite it as a pre-public-tooling release: a different tree, so a different identity, but resolvable.
        shutil.rmtree(root / "releases")
        files = release_files(fmt="dpinfra.config-release/v1")
        for rel, data in files.items():
            (root / "releases" / VERSION / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / "releases" / VERSION / rel).write_bytes(data)
        legacy = infra_release.digest_of(files)
        self.assertNotEqual(legacy, hexd)
        idx = {
            "schema_version": 1,
            "releases": [{"version": VERSION, "digest": legacy, "contract": "dev-platform.infra/v1"}],
        }
        (root / infra_release.INDEX).write_bytes(infra_release.index_bytes(idx))
        write_policy(root)
        res = infra_provider.resolve(root, request(digest="sha256:" + legacy))
        self.assertEqual(res["result"]["decision"], "resolved")


class Narrowing(Base):
    def test_policy_narrows_an_older_pin_and_moves_only_the_profile_digest(self):
        a = self.go()
        write_policy(self.root, revision=2, withdrawn={"runner_classes": [], "credentials": ["deploy"]})
        b = self.go()
        self.assertEqual(a["result"]["resolved"], b["result"]["resolved"])
        self.assertNotEqual(a["result"]["effective_profile_digest"], b["result"]["effective_profile_digest"])
        self.assertEqual(b["evidence"]["narrowed_by_policy"], ["credential:linux-trusted:deploy"])
        self.assertEqual(self.judged(b).status, "resolved")
        self.assertTrue(infra_authz.is_narrower(b["profile"], a["profile"]))

    def test_withdrawn_runner_and_per_repository_withdrawal(self):
        write_policy(self.root, repository_withdrawn={"app": {"runner_classes": ["linux-trusted"]}})
        res = self.go()
        self.assertEqual([r["id"] for r in res["profile"]["runners"]], ["linux-public"])
        tool = self.go(repo=f"{OWNER}/tool")
        self.assertEqual(tool["evidence"]["narrowed_by_policy"], [])

    def test_a_profile_file_pin_refuses_a_narrowed_profile(self):
        first = self.go()
        file_pin = first["result"]["effective_profile_digest"]
        write_policy(self.root, revision=2, withdrawn={"runner_classes": [], "credentials": ["signing"]})
        r = self.judged(self.go(), digest=file_pin, kind="profile-file")
        self.assertEqual(r.status, "unavailable")

    def test_the_policy_format_cannot_grant(self):
        for key in ("granted", "added_runners", "credentials", "repositories"):
            self.assertTrue(infra_authz.problems({**policy(), key: []}), key)
        write_policy(self.root, granted={"credentials": ["root"]})
        self.assertEqual(self.code(self.go()), "policy-invalid")

    def test_narrowing_never_widens(self):
        release = json.loads((self.root / "releases" / VERSION / "profiles" / "app.json").read_text())
        for withdrawn in ([], ["deploy"], ["deploy", "signing", "unknown"]):
            for runners in ([], ["linux-trusted"], ["linux-public", "linux-trusted"]):
                pol = policy(withdrawn={"runner_classes": runners, "credentials": withdrawn})
                eff, _ = infra_authz.narrow(release, pol, "app")
                self.assertTrue(infra_authz.is_narrower(eff, release), (withdrawn, runners))
        widened = json.loads(json.dumps(release))
        widened["runners"][0]["credentials"].append("root")
        self.assertFalse(infra_authz.is_narrower(widened, release))
        widened = json.loads(json.dumps(release))
        widened["runners"][1]["trust"] = "trusted"
        self.assertFalse(infra_authz.is_narrower(widened, release))


class Denies(Base):
    CASES = {
        "release-stale": dict(policy=dict(minimum_release="2026.02.1")),
        "release-revoked": dict(policy=dict(revoked_releases=[{"version": VERSION, "reason": "unsafe"}])),
        "repo-not-enabled": dict(policy=dict(repositories_enabled=["tool"])),
    }

    def test_current_policy_denies(self):
        for code, case in self.CASES.items():
            write_policy(self.root, **case["policy"])
            res = self.go()
            self.assertEqual((res["result"]["decision"], self.code(res)), ("denied", code))
            self.assertIsNone(res["profile_bytes"])
            self.assertEqual(self.judged(res).status, "unavailable", code)

    def test_a_consumer_pin_cannot_override_revocation(self):
        write_policy(self.root, revoked_releases=[{"version": VERSION}])
        self.assertEqual(self.code(self.go()), "release-revoked")
        self.assertEqual(self.code(self.go(version="2026.02.1", digest=self.digests["2026.02.1"])), None)

    def test_missing_or_invalid_policy_fails_closed(self):
        p = self.root / infra_provider.POLICY
        for content in (
            None,
            "not json",
            "{}",
            json.dumps(policy(revision=0)),
            json.dumps(policy(revision=True)),
        ):
            if content is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(content)
            res = self.go()
            self.assertEqual(self.code(res), "policy-invalid", content)
            self.assertEqual(self.judged(res).status, "unavailable")
        # without a policy even an untrusted request is not answered with a default
        p.unlink()
        self.assertEqual(self.code(self.go(trust="untrusted")), "policy-invalid")

    def test_selection_must_be_exact(self):
        for kw, code in (
            (dict(digest="sha256:" + "0" * 64), "digest-mismatch"),
            (dict(version="2026.03.1"), "version-unknown"),
            (dict(version="latest"), "request-invalid"),
            (dict(digest="0" * 64), "request-invalid"),
            (dict(requested={"version": VERSION}), "selection-missing"),
            (dict(requested=None), "selection-missing"),
        ):
            self.assertEqual(self.code(self.go(**kw)), code, kw)

    def test_malformed_requests(self):
        for req in (
            None,
            [],
            "x",
            {**request(), "extra": 1},
            request(repo="no-slash"),
            request(trust="maybe"),
            {**request(), "schema_version": "dev-platform.infra-resolve-request/v2"},
        ):
            res = infra_provider.resolve(self.root, req)
            self.assertEqual(self.code(res), "request-invalid", req)

    def test_other_owner_and_unassigned_repository(self):
        self.assertEqual(self.code(self.go(repo="someone-else/app")), "repo-not-enabled")
        write_policy(self.root, repositories_enabled=["app", "tool", "other"])
        self.assertEqual(self.code(self.go(repo=f"{OWNER}/other")), "repo-not-in-release")

    def test_unsupported_contract(self):
        self.assertEqual(self.code(self.go(contract="dev-platform.infra/v2")), "unsupported-contract")

    def test_tampered_release(self):
        p = self.root / "releases" / VERSION / "profiles" / "app.json"
        p.write_bytes(p.read_bytes().replace(b"x86_64", b"arm64"))
        self.assertEqual(self.code(self.go()), "release-tampered")

    def test_content_that_is_not_plain_files_is_unreadable(self):
        # The same code as the provider the generic one replaces (#140): symlink, special file, no directory.
        d = self.root / "releases" / VERSION
        os.symlink("/etc/hosts", d / "profiles" / "link.json")
        self.assertEqual(self.code(self.go()), "release-unreadable")
        (d / "profiles" / "link.json").unlink()
        os.mkfifo(d / "fifo")
        self.assertEqual(self.code(self.go()), "release-unreadable")
        (d / "fifo").unlink()
        shutil.move(d, self.root / "moved")
        self.assertEqual(self.code(self.go()), "release-unreadable")

    def test_generated_files_in_a_release_are_tampering(self):
        (self.root / "releases" / VERSION / "x.pyc").write_bytes(b"")
        self.assertEqual(self.code(self.go()), "release-tampered")

    def test_tampered_index(self):
        (self.root / infra_release.INDEX).write_text("{")
        self.assertEqual(self.code(self.go()), "index-invalid")


class Untrusted(Base):
    def test_no_release_is_read(self):
        shutil.rmtree(self.root / "releases")
        res = self.go(trust="untrusted")
        self.assertEqual(res["result"]["decision"], "public-default")
        self.assertIsNone(res["profile_bytes"])
        pin = InfraPin("example-infra", VERSION, self.digest)
        r = infra.evaluate(
            pin, infra.request_for(pin, repo="o/r", event_trust="untrusted"), res["result"], None
        )
        self.assertEqual(r.status, "hosted-only")


class Command(Base):
    """The real command, driven through the engine's own run_resolver."""

    def run_resolver(self, trust="trusted", digest=None):
        pin = InfraPin("example-infra", VERSION, digest or self.digest, "release-tree")
        argv = [sys.executable, "-m", "dev_platform", "infra", "resolve", "--root", str(self.root)]
        old = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = str(ROOT / "src")
        try:
            return infra.run_resolver(pin, argv, repo=f"{OWNER}/app", event_trust=trust, scratch=tmpdir(self))
        finally:
            os.environ.pop("PYTHONPATH") if old is None else os.environ.__setitem__("PYTHONPATH", old)

    def test_engine_resolves_through_the_cli(self):
        r = self.run_resolver()
        self.assertEqual(r.status, "resolved", r.reasons)
        self.assertEqual(stat.S_IMODE(r.profile_path.stat().st_mode), 0o600)
        self.assertEqual(r.evidence()["pinned"]["config_digest_kind"], "release-tree")

    def test_a_denial_exits_zero_and_the_engine_blocks(self):
        r = self.run_resolver(digest="sha256:" + "1" * 64)
        self.assertEqual(r.status, "unavailable")
        self.assertTrue(r.blocks)

    def test_untrusted_never_writes_a_profile(self):
        out = tmpdir(self) / "p.json"
        req = request(trust="untrusted", digest=self.digest, profile_out=str(out))
        p = subprocess.run(
            [sys.executable, "-m", "dev_platform", "infra", "resolve", "--root", str(self.root)],
            input=json.dumps(req),
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["decision"], "public-default")
        self.assertFalse(out.exists())

    def test_profile_out_is_never_followed_through_a_symlink(self):
        target = tmpdir(self) / "target"
        target.write_text("keep")
        link = tmpdir(self) / "link.json"
        os.symlink(target, link)
        with self.assertRaises(OSError):
            infra_provider.write_private(str(link), b"x")
        self.assertEqual(target.read_text(), "keep")

    def test_release_verify_and_digest_commands(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        run = lambda *a: subprocess.run(
            [sys.executable, "-m", "dev_platform", "infra", *a], capture_output=True, text=True, env=env
        )
        p = run("release", "verify", "--root", str(self.root))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = run("digest", str(self.root / "releases" / VERSION))
        self.assertEqual(p.stdout.strip(), self.digest)
        (self.root / "releases" / VERSION / "extra").write_text("x")
        self.assertEqual(run("release", "verify", "--root", str(self.root)).returncode, 1)
        p = run("authorization", "check", str(self.root / infra_provider.POLICY))
        self.assertEqual(json.loads(p.stdout)["identity"], infra_authz.identity(policy()))


if __name__ == "__main__":
    unittest.main()
