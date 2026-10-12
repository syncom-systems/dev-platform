"""The reference provider and the engine agree on the wire format and on fail-closed behaviour (issue #99)."""

import os
import sys
import unittest

from dev_platform import infra
from dev_platform.config import InfraPin
from tests.helpers import ROOT, tmpdir

KIT = ROOT / "contracts" / "infra" / "v1"
PROFILE = KIT / "valid-trusted-credentials.json"
DIGEST = infra.file_digest(PROFILE)


class Reference(unittest.TestCase):
    def resolve(self, pin=None, repo="o/r", trust="trusted", allowed="o/r", release="1.4.0"):
        pin = pin or InfraPin("ref", "1.4.0", DIGEST)
        env = {"REF_PROFILE": str(PROFILE), "REF_RELEASE": release, "REF_ALLOWED_REPOS": allowed}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            return infra.resolve(pin, event_trust=trust, repo=repo, profile_file=None,
                                 resolver_argv=[sys.executable, str(KIT / "reference-resolver.py")],
                                 scratch=tmpdir(self))  # fmt: skip
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_resolves_the_pinned_release(self):
        r = self.resolve()
        self.assertEqual((r.status, r.source), ("resolved", "resolver"))
        self.assertEqual(r.effective_profile_digest, DIGEST)

    def test_unauthorized_repository_is_denied_and_blocks(self):
        r = self.resolve(repo="x/y")
        self.assertEqual(r.status, "unavailable")
        self.assertTrue(r.blocks)

    def test_a_different_pin_than_the_one_served_is_unavailable(self):
        self.assertEqual(self.resolve(pin=InfraPin("ref", "1.5.0", DIGEST)).status, "unavailable")
        self.assertEqual(
            self.resolve(pin=InfraPin("ref", "1.4.0", "sha256:" + "a" * 64)).status, "unavailable"
        )

    def test_untrusted_event_never_reaches_the_provider(self):
        self.assertEqual(self.resolve(trust="untrusted").status, "hosted-only")


if __name__ == "__main__":
    unittest.main()
