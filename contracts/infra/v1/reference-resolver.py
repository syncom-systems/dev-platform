#!/usr/bin/env python3
"""Reference provider for the dev-platform.infra-resolve request/result contract (ADR 0021, #99).

A conformance aid, not a product: it serves ONE vendored profile as ONE configuration release.
A real provider keeps its own authorization policy; this shows the wire format and the fail-closed
behaviour the platform expects.

  REF_PROFILE=profile.json REF_RELEASE=1.4.0 REF_ALLOWED_REPOS=owner/repo,owner/other \\
    dev-platform check --infra-resolver "python3 reference-resolver.py" --event-trust trusted ...

stdin: dev-platform.infra-resolve-request/v1
  {schema_version, repo, event_trust, contract, requested{version,digest}, profile_out}
stdout: dev-platform.infra-resolve-result/v1; the profile is written to `profile_out`.
"""

import hashlib
import json
import os
import sys

req = json.load(sys.stdin)
with open(os.environ["REF_PROFILE"], "rb") as f:
    data = f.read()
digest = "sha256:" + hashlib.sha256(data).hexdigest()
release = os.environ["REF_RELEASE"]
allowed = [r for r in os.environ.get("REF_ALLOWED_REPOS", "").split(",") if r]
out = {
    "schema_version": "dev-platform.infra-resolve-result/v1",
    "contract": "dev-platform.infra/v1",
    "requested": req["requested"],
    "reasons": [],
    "resolved": None,
    "authorization_policy": {"id": "reference", "revision": "1", "digest": "sha256:" + "0" * 64},
}
if req.get("event_trust") != "trusted":
    out |= {"decision": "public-default", "reasons": ["untrusted event: hosted runners only"]}
elif allowed and req.get("repo") not in allowed:
    out |= {"decision": "denied", "reasons": ["repository is not authorized for this configuration"]}
elif req["requested"] != {"version": release, "digest": digest}:
    out |= {"decision": "denied", "reasons": ["requested configuration release is not served"]}
else:
    with open(req["profile_out"], "wb") as f:
        f.write(data)
    out |= {"decision": "resolved", "resolved": req["requested"], "effective_profile_digest": digest}
print(json.dumps(out))
