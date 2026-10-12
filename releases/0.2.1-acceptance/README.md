# Acceptance of dev-platform v0.2.1 (scope `platform-baseline`)

Accepted on 2026-10-12 by the owner (`matssun`) through ADR 0020: run 38243980560 of the manual `accept` workflow was approved
on the `owner-approval` environment; the workflow attested the record `authorizations/platform-0.2.1-approved-38243980560.json`.

Verified with `tools/verify_release.py` (`a2d53075…6f2e`) and v0.2.1's own policy plus the owner as approver
(`trust-policy.json`, sha256 `ba88ae61…0c0d`, merged in #104 and pinned out of band by the owner):
`evidence/verification.owner.json` (record supplied) and `evidence/current.owner.json` (current-state check against GitHub at
evidence commit `1d0dd98`: `accepted`). `evidence/approvals.json` is GitHub's recording of the approval; `evidence/pins.txt` the digests used.

What this confers: `platform-baseline` for archive `3cc47abb…2044` only. It is not certification, not an application approval,
and not an acceptance of 0.3.0-0.7.0 (separate archives). The immutable release and `releases/0.2.1/` are unchanged.

Limits: the approval is as strong as the owner's GitHub login at the click (agents using the same session cannot be told
apart); "current" means GitHub's state when the check ran and is valid for `currency.valid_until` (5 minutes); re-run the
current-state check for any decision that depends on it. A revocation is another `accept` run with decision `revoked`.
