import itertools
import unittest

from dev_platform.model import EvidenceState as S
from dev_platform.model import Outcome as O
from dev_platform.model import advance


class EvidenceStateMachineTest(unittest.TestCase):
    PREV = [None, *S]

    def test_verified_requires_pass_or_unimpacted_carry(self):
        for prev, impacted, outcome in itertools.product(self.PREV, (True, False), O):
            got = advance(prev, impacted=impacted, outcome=outcome)
            if got is S.VERIFIED:
                carried = prev is S.VERIFIED and not impacted and outcome is not O.FAILED
                self.assertTrue(outcome is O.PASSED or carried, (prev, impacted, outcome))

    def test_impacted_and_not_passed_is_never_verified(self):
        for prev, outcome in itertools.product(self.PREV, (O.UNAVAILABLE, O.NOT_RUN, O.FAILED)):
            self.assertIsNot(advance(prev, impacted=True, outcome=outcome), S.VERIFIED)

    def test_failure_persists_until_pass(self):
        for impacted in (True, False):
            self.assertIs(advance(S.FAILED, impacted=impacted, outcome=O.NOT_RUN), S.FAILED)
        self.assertIs(advance(S.FAILED, impacted=True, outcome=O.PASSED), S.VERIFIED)

    def test_invalidation(self):
        self.assertIs(advance(S.VERIFIED, impacted=True, outcome=O.NOT_RUN), S.INVALIDATED)
        self.assertIs(advance(S.VERIFIED, impacted=False, outcome=O.NOT_RUN), S.VERIFIED)
        self.assertIs(advance(S.INVALIDATED, impacted=False, outcome=O.NOT_RUN), S.INVALIDATED)

    def test_slow_unrun_check_is_pending_not_realized(self):
        self.assertIs(advance(None, impacted=False, outcome=O.NOT_RUN), S.PENDING)
        self.assertIs(advance(None, impacted=True, outcome=O.UNAVAILABLE), S.PENDING)


if __name__ == "__main__":
    unittest.main()
