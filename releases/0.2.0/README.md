# 0.2.0 (verified-unaccepted; retained, superseded by 0.2.1)

Published as an immutable pre-release flagged "verified, NOT accepted". Independent verification (verifier from
main, operator pins) passed 32/32 checks including predecessor continuity; `confers: []`. No authorization exists.

| | |
|---|---|
| Tag / revision | v0.2.0 / cfc87c284dd447fbfb3675357d1e535c793fc23f |
| Archive sha256 | 2eeeab1e7e9ee962bdfab2e18b1d2856c942b6e2a29290a252064e7329a103d3 |
| Tree digest | 054f2c9a7742ac4d307ef9942c15367cb8b80cc25ef485c3da32615e42f98539 |
| Release workflow run | https://github.com/syncom-systems/dev-platform/actions/runs/38156034769 |
| Predecessor (policy pin) | 0.1.2 (verified-unaccepted); its full stage over this source passed |

## Why it is not the recommended candidate
Independent verification exercised the trusted installer and found a defect in the installer shipped at this
tag: `tools/install_release.py` never downloaded or passed the continuity record, so installing any release whose
policy names a predecessor failed closed ("verification failed: continuity"). The verifier was right to refuse;
the installer could not supply the evidence. Fixed in the next release (0.2.1); with the fixed installer this very
artifact installs and stays verified-unaccepted (see `rejections.txt`). The artifact itself is unchanged and
valid; the tag cannot be edited (immutable), so a consumer following this tag's own tooling is stuck.
Use 0.2.1. Nothing here was accepted or certified.

Records: verification.ci.json, verification.independent.json, continuity.json, build-environment.json,
rejections.txt (live negatives: invented provider, wrong revision, appended byte, absent/altered continuity
record, installer refusal, wrong verifier pin).
