import json
import unittest

from dev_platform.config import RunnerSpec
from dev_platform.errors import ConfigError
from dev_platform.runners import INFRA_SCHEMA, load_profile, route
from tests.helpers import tmpdir

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


if __name__ == "__main__":
    unittest.main()
