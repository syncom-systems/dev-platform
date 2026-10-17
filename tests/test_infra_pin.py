"""Consumer-owned infra configuration pin: parsing, resolution semantics, evidence, conformance cases.

The resolver is a real subprocess (a tiny provider script) so the request/response contract is exercised end to end.
"""

import json
import sys
import textwrap
import unittest

from dev_platform import engine, infra
from dev_platform.config import parse
from dev_platform.errors import ConfigError
from dev_platform.model import Stage
from dev_platform.resolve import Resolution
from tests.helpers import ROOT, tmpdir

KIT = ROOT / "contracts" / "infra" / "v1"
PROFILE = KIT / "valid-trusted-credentials.json"
DIGEST = infra.file_digest(PROFILE)
TOML = {
    "schema_version": 1,
    "platform": {"self_hosted": True},
    "project": {"name": "x"},
    "check": [
        {"id": "t", "adapter": "exec", "argv": ["true"], "stages": ["pre-merge", "full"], "inputs": ["**"]}
    ],
}


def cfg(**infra_table):
    d = dict(TOML)
    if infra_table:
        d["infra"] = infra_table
    return parse(d)


PIN = {"provider": "acme-infra", "config_release": "1.4.0", "config_digest": DIGEST}


class Pin(unittest.TestCase):
    def test_absent_means_hosted_only(self):
        self.assertIsNone(cfg().infra)

    def test_exact_release_and_digest_are_required(self):
        for bad in (
            {**PIN, "config_release": "latest"},
            {**PIN, "config_release": "^1.4"},
            {**PIN, "config_digest": "abc"},
            {**PIN, "config_digest": "sha256:" + "A" * 64},
            {"provider": "acme-infra", "config_release": "1.4.0"},
            {**PIN, "surprise": "x"},
        ):
            with self.assertRaises(ConfigError, msg=str(bad)):
                cfg(**bad)

    def test_valid_pin(self):
        self.assertEqual(cfg(**PIN).infra.config_release, "1.4.0")


class Resolution_(unittest.TestCase):
    def setUp(self):
        self.pin = cfg(**PIN).infra
        self.scratch = tmpdir(self)

    def resolve(self, **kw):
        base = {"event_trust": "trusted", "repo": "o/r", "profile_file": None, "resolver_argv": None}
        return infra.resolve(self.pin, scratch=self.scratch, **{**base, **kw})

    def test_vendored_profile_with_the_pinned_digest_is_resolved(self):
        r = self.resolve(profile_file=PROFILE)
        self.assertEqual((r.status, r.source), ("resolved", "vendored-file"))
        self.assertEqual(r.effective_profile_digest, DIGEST)

    def test_vendored_profile_with_another_digest_is_unavailable(self):
        other = tmpdir(self) / "p.json"
        other.write_text(PROFILE.read_text().replace('"trusted"', '"trusted" ', 1))
        r = self.resolve(profile_file=other)
        self.assertEqual(r.status, "unavailable")
        self.assertTrue(r.blocks)

    def test_pin_without_any_source_is_unavailable_never_silently_hosted(self):
        self.assertEqual(self.resolve().status, "unavailable")

    def test_untrusted_events_never_invoke_a_provider(self):
        marker = self.scratch / "called"
        script = self.scratch / "prov.py"
        script.write_text(f"open({str(marker)!r}, 'w').write('x')\n")
        r = self.resolve(event_trust="untrusted", resolver_argv=[sys.executable, str(script)])
        self.assertEqual(r.status, "hosted-only")
        self.assertFalse(marker.exists())
        self.assertFalse(r.blocks)

    def test_untrusted_events_use_only_a_vendored_profile_that_equals_the_pin(self):
        self.assertEqual(self.resolve(event_trust="untrusted", profile_file=PROFILE).status, "resolved")
        other = tmpdir(self) / "p.json"
        other.write_text("{}")
        self.assertEqual(self.resolve(event_trust="untrusted", profile_file=other).status, "unavailable")

    def test_profile_or_resolver_without_a_pin_is_not_used(self):
        r = infra.resolve(
            None,
            event_trust="trusted",
            repo=None,
            profile_file=PROFILE,
            resolver_argv=None,
            scratch=self.scratch,
        )
        self.assertEqual(r.status, "unpinned")
        self.assertIsNone(r.profile)
        self.assertTrue(r.blocks)
        self.assertEqual(
            infra.resolve(
                None,
                event_trust="trusted",
                repo=None,
                profile_file=None,
                resolver_argv=None,
                scratch=self.scratch,
            ).status,
            "hosted-only",
        )

    def provider(self, body):
        script = self.scratch / "prov.py"
        script.write_text(textwrap.dedent(body))
        return [sys.executable, str(script)]

    def test_resolver_round_trip(self):
        argv = self.provider(
            f"""
            import hashlib, json, sys
            req = json.load(sys.stdin)
            assert req["schema_version"] == "dev-platform.infra-resolve-request/v1"
            assert req["contract"] == "dev-platform.infra/v1" and req["event_trust"] == "trusted"
            data = open({str(PROFILE)!r}, "rb").read()
            open(req["profile_out"], "wb").write(data)
            print(json.dumps({{
                "schema_version": "dev-platform.infra-resolve-result/v1", "decision": "resolved", "reasons": [],
                "requested": req["requested"], "resolved": req["requested"],
                "authorization_policy": {{"id": "p", "revision": "1", "digest": "sha256:" + "0" * 64}},
                "effective_profile_digest": "sha256:" + hashlib.sha256(data).hexdigest()}}))
            """
        )
        r = self.resolve(resolver_argv=argv)
        self.assertEqual((r.status, r.source), ("resolved", "resolver"))
        self.assertEqual(r.authorization_policy["id"], "p")
        self.assertEqual(r.profile_path.read_bytes(), PROFILE.read_bytes())

    def test_resolver_failures_are_unavailable(self):
        for body in ("import sys; sys.exit(3)", "print('not json')", "import time; time.sleep(0)"):
            r = self.resolve(resolver_argv=self.provider(body))
            self.assertEqual(r.status, "unavailable", body)
        self.assertEqual(self.resolve(resolver_argv=["/nonexistent/provider"]).status, "unavailable")

    def test_evidence_never_contains_profile_contents(self):
        r = self.resolve(profile_file=PROFILE)
        ev = json.dumps(r.evidence())
        for word in json.loads(PROFILE.read_text())["runners"][0]["labels"]:
            self.assertNotIn(f'"{word}"', ev)


class DigestKind(unittest.TestCase):
    """What `config_digest` identifies is explicit when declared, and unchanged when not (ADR 0023)."""

    def setUp(self):
        self.scratch = tmpdir(self)

    def resolve(self, kind, **kw):
        pin = cfg(**PIN, config_digest_kind=kind).infra if kind else cfg(**PIN).infra
        base = {"event_trust": "trusted", "repo": "o/r", "profile_file": None, "resolver_argv": None}
        return infra.resolve(pin, scratch=self.scratch, **{**base, **kw})

    def test_values(self):
        self.assertEqual(
            cfg(**PIN, config_digest_kind="release-tree").infra.config_digest_kind, "release-tree"
        )
        self.assertIsNone(cfg(**PIN).infra.config_digest_kind)
        for bad in ("tree", "", "latest", 1):
            with self.assertRaises(ConfigError, msg=bad):
                cfg(**PIN, config_digest_kind=bad)

    def test_a_release_tree_pin_never_matches_a_vendored_profile(self):
        for trust in ("trusted", "untrusted"):
            r = self.resolve("release-tree", profile_file=PROFILE, event_trust=trust)
            self.assertEqual(r.status, "unavailable", trust)
            self.assertIn("release-tree", " ".join(r.reasons))

    def test_a_profile_file_pin_and_no_kind_accept_the_vendored_profile(self):
        for kind in ("profile-file", None):
            self.assertEqual(self.resolve(kind, profile_file=PROFILE).status, "resolved", kind)

    def test_evidence_names_the_kind_only_when_declared(self):
        self.assertEqual(
            self.resolve("profile-file", profile_file=PROFILE).evidence()["pinned"]["config_digest_kind"],
            "profile-file",
        )
        self.assertNotIn("config_digest_kind", self.resolve(None, profile_file=PROFILE).evidence()["pinned"])


class AuthorizationFacts(unittest.TestCase):
    def test_complete_identity_only(self):
        ok = {"id": "p", "revision": "1", "digest": "sha256:" + "0" * 64}
        self.assertIsNone(infra.authorization_facts(ok))
        for bad in (
            None,
            {},
            {**ok, "extra": 1},
            {**ok, "revision": 1},
            {**ok, "id": ""},
            {**ok, "digest": "x"},
            {"id": "p", "revision": "1"},
        ):
            self.assertIsNotNone(infra.authorization_facts(bad), bad)


class Conformance(unittest.TestCase):
    def test_every_resolution_case(self):
        self.assertEqual(infra.conformance(KIT / "resolution-cases.json", KIT), [])


class InEngine(unittest.TestCase):
    def build(self, infra_res, execute=True, stage=Stage.FULL):
        c = cfg(**PIN)
        res = Resolution("self", None, None, None)
        return engine.build(
            c,
            tmpdir(self),
            res,
            stage,
            ("a.txt",),
            execute=execute,
            executor=lambda cmd, root: 0,
            infra=infra_res,
        )

    def test_unavailable_pin_blocks_admission_and_certification(self):
        r = infra.InfraResolution("unavailable", "none", ["no source"], cfg(**PIN).infra)
        doc = self.build(r)
        self.assertIn("infra", doc["unsatisfied_obligations"])
        self.assertEqual(doc["admission"], "blocked")
        self.assertTrue(any("infrastructure configuration" in b for b in doc["certification"]["blockers"]))
        self.assertEqual(doc["infra"]["status"], "unavailable")

    def test_resolved_pin_is_recorded_and_does_not_block(self):
        r = infra.from_vendored_file(cfg(**PIN).infra, PROFILE)
        doc = self.build(r)
        self.assertNotIn("infra", doc["unsatisfied_obligations"])
        self.assertEqual(doc["infra"]["pinned"]["config_release"], "1.4.0")
        self.assertEqual(doc["infra"]["effective_profile_digest"], DIGEST)

    def test_unpinned_profile_blocks_certification_only(self):
        r = infra.InfraResolution("unpinned", "none", ["no pin"], None)
        doc = self.build(r)
        self.assertNotIn("infra", doc["unsatisfied_obligations"])
        self.assertTrue(any("infrastructure configuration" in b for b in doc["certification"]["blockers"]))


if __name__ == "__main__":
    unittest.main()
