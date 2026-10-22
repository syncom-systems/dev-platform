import json
import unittest

from dev_platform.config import RunnerSpec
from dev_platform.errors import ConfigError
from dev_platform.runners import INFRA_SCHEMA, RUNNER_KINDS, load_profile, route, validate_profile
from tests.helpers import ROOT, tmpdir

PRIVATE = {
    "schema": INFRA_SCHEMA,
    "runners": [
        {
            "id": "mini",
            "labels": ["self-hosted", "macOS"],
            "os": "macos",
            "arch": "arm64",
            "isolation": "persistent",
            "trust": "trusted",
            "credentials": ["deploy"],
        }
    ],
}


def profile(test, doc):
    p = tmpdir(test) / "infra.json"
    p.write_text(json.dumps(doc))
    return load_profile(p)


class RunnerTest(unittest.TestCase):
    def test_public_default_needs_no_private_infra(self):
        r = route(RunnerSpec("r", os="linux"), load_profile(None), "untrusted")
        self.assertTrue(r.ok)
        self.assertEqual(r.labels, ("ubuntu-24.04",))

    def test_private_runner_preferred_for_trusted_events(self):
        offered = profile(self, PRIVATE)
        r = route(RunnerSpec("r", os="macos", arch="arm64"), offered, "trusted")
        self.assertEqual(r.runner_id, "mini")

    def test_untrusted_event_never_reaches_private_runner(self):
        offered = profile(self, PRIVATE)
        r = route(RunnerSpec("r", os="macos", arch="arm64"), offered, "untrusted")
        self.assertEqual(r.runner_id, "github-macos")

    def test_credentials_never_for_untrusted(self):
        r = route(RunnerSpec("r", credentials=("deploy",)), profile(self, PRIVATE), "untrusted")
        self.assertFalse(r.ok)

    def test_unsatisfiable_requirement_is_not_silently_downgraded(self):
        r = route(
            RunnerSpec("r", isolation="ephemeral", credentials=("deploy",)), profile(self, PRIVATE), "trusted"
        )
        self.assertFalse(r.ok)  # the only runner with the credential is persistent

    def test_fallback_none_refuses_hosted(self):
        r = route(RunnerSpec("r", os="linux", fallback="none"), load_profile(None), "trusted")
        self.assertFalse(r.ok)

    def test_bad_profile_rejected(self):
        with self.assertRaises(ConfigError):
            profile(self, {"schema": "wrong"})
        with self.assertRaises(ConfigError):
            profile(self, {"schema": INFRA_SCHEMA, "runners": [{"id": "x"}]})

    def test_bad_trust_input_rejected(self):
        with self.assertRaises(ConfigError):
            route(RunnerSpec("r"), load_profile(None), "maybe")


HOSTED = {
    "id": "example-hosted",
    "kind": "hosted",
    "labels": ["ubuntu-24.04"],
    "os": "linux",
    "arch": "x86_64",
    "isolation": "ephemeral",
    "trust": "public",
    "capabilities": ["docker"],
}
SELF = {
    "id": "example-self",
    "labels": ["example-fast"],
    "os": "linux",
    "arch": "x86_64",
    "isolation": "persistent",
    "trust": "trusted",
    "capabilities": ["docker"],
}


class ProviderRunnerKind(unittest.TestCase):
    """A provider can mark a runner GitHub-hosted; absent kind stays self-hosted."""

    def offered(self, *runners):
        return profile(self, {"schema": INFRA_SCHEMA, "runners": list(runners)})

    def test_fallback_none_excludes_a_provider_hosted_runner(self):
        o = self.offered(HOSTED, SELF)
        self.assertEqual(route(RunnerSpec("j", fallback="none"), o, "trusted").runner_id, "example-self")
        r = route(RunnerSpec("j", fallback="none", isolation="ephemeral"), o, "trusted")
        self.assertFalse(r.ok)
        self.assertIn("fallback: hosted runners excluded", r.reason)

    def test_default_fallback_still_offers_it_and_untrusted_events_still_reach_it(self):
        o = self.offered(HOSTED, SELF)
        self.assertEqual(
            route(RunnerSpec("j", isolation="ephemeral"), o, "trusted").runner_id, "example-hosted"
        )
        self.assertEqual(route(RunnerSpec("j"), o, "untrusted").runner_id, "example-hosted")

    def test_a_profile_without_kind_is_unchanged(self):
        o = self.offered(SELF)
        self.assertEqual(o[0]["kind"], "self-hosted")
        self.assertEqual(route(RunnerSpec("j", fallback="none"), o, "trusted").runner_id, "example-self")

    def test_provider_order_is_a_preference_never_an_override(self):
        # the hosted runner is listed first (preferred), yet requirements and restrictions still win
        o = self.offered(HOSTED, SELF)
        self.assertEqual(route(RunnerSpec("j"), o, "trusted").runner_id, "example-hosted")
        self.assertEqual(route(RunnerSpec("j", fallback="none"), o, "trusted").runner_id, "example-self")
        self.assertEqual(
            route(RunnerSpec("j", isolation="persistent"), o, "trusted").runner_id, "example-self"
        )
        self.assertFalse(route(RunnerSpec("j", credentials=("c",)), o, "trusted").ok)

    def test_kind_is_validated(self):
        def bad(r):
            return validate_profile({"schema": INFRA_SCHEMA, "runners": [r]})

        self.assertTrue(bad({**HOSTED, "kind": "cloud"}))
        self.assertTrue(bad({**HOSTED, "isolation": "persistent"}))
        self.assertTrue(bad({**HOSTED, "trust": "trusted"}))
        self.assertTrue(bad({**HOSTED, "trust": "trusted", "credentials": ["example-credential"]}))
        self.assertEqual(bad(HOSTED), [])
        self.assertEqual(bad({**SELF, "kind": "self-hosted"}), [])

    def test_schema_agrees_with_the_validator(self):
        # the JSON Schema is the published contract: it must reject what the code rejects
        schema = json.loads((ROOT / "schemas" / "infra-profile-v1.schema.json").read_text())
        r = schema["properties"]["runners"]["items"]
        self.assertEqual(r["properties"]["kind"]["enum"], list(RUNNER_KINDS))
        hosted = r["allOf"][0]["then"]["properties"]
        self.assertEqual(
            (hosted["isolation"]["const"], hosted["trust"]["const"], hosted["credentials"]["maxItems"]),
            ("ephemeral", "public", 0),
        )


if __name__ == "__main__":
    unittest.main()
