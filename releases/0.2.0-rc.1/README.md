# 0.2.0-rc.1 (pre-release rehearsal; never accepted)

First release carrying a predecessor-continuity record (issue #4).

| | |
|---|---|
| Tag / revision | v0.2.0-rc.1 / dcb05aeb4bce9167ee118d069c9c626aa6dcc113 |
| Archive sha256 | 8579f561585c50b527786e6a68ef429430b4840357d90154ba86424e17b8e3b4 |
| Release workflow run | https://github.com/syncom-systems/dev-platform/actions/runs/38153105637 |
| Predecessor (policy pin) | 0.1.2, archive d8aee299..., tree acd586da... |
| Pins used | verify_release.py 791713d0..., policy a0cb10a0..., install_release.py 7e98915b... |

Independent verification (verifier from main, operator pins): all checks passed incl. continuity and
continuity-attestation; state pre-release. Negatives: no continuity record -> failed; a one-byte edit of the record
-> attestation failure; a record whose stage exit is 1 -> failed. No authorization was created.
