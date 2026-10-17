"""The generic provider is compatible with the engines of older supported platform releases (ADR 0023).

A consumer pins an exact platform release; its engine, not this one, judges a provider's result. So every result the
provider produces is judged here by the `infra.evaluate` and `validate_profile` of each released engine that speaks
the resolver contract (0.8.0 and later), taken from the release tag. Needs the tags (a full clone, as in CI).
"""

import io
import json
import os
import subprocess
import sys
import tarfile
import unittest

from dev_platform import infra, infra_provider
from dev_platform.config import InfraPin, parse_pin
from tests.helpers import ROOT, tmpdir
from tests.infra_fixtures import OWNER, VERSION, config_repo, request, write_policy

RELEASES = ("v0.8.0", "v0.8.1", "v0.8.2", "v0.9.0")

DRIVER = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from dev_platform import infra, runners
from dev_platform.config import InfraPin, parse_pin
out = []
for c in json.load(open(sys.argv[2])):
    errs = []
    pin = parse_pin(c["pin"], errs)
    data = bytes.fromhex(c["profile"]) if c["profile"] is not None else None
    r = infra.evaluate(pin, infra.request_for(pin, repo=c["repo"], event_trust=c["trust"]), c["result"], data)
    valid = runners.validate_profile(json.loads(data)) if data else None
    out.append({"status": r.status, "profile_problems": valid, "pin_errors": errs})
print(json.dumps(out))
"""


def _tags_available() -> bool:
    p = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", *RELEASES], capture_output=True, text=True)
    return p.returncode == 0 and set(p.stdout.split()) == set(RELEASES)


def _extract(tag: str, dest):
    data = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", tag, "src/dev_platform"],
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        tf.extractall(dest, filter="data")
    return dest / "src"


IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"


@unittest.skipUnless(_tags_available() or IN_CI, "release tags not available (shallow clone)")
class OlderEngines(unittest.TestCase):
    def setUp(self):
        self.assertTrue(_tags_available(), "CI must provide the release tags (fetch-depth: 0)")
        self.root = tmpdir(self)
        self.digests = config_repo(self.root, versions=(VERSION, "2026.02.1"))

    def cases(self):
        d = self.digests[VERSION]
        pin = {"provider": "example-infra", "config_release": VERSION, "config_digest": d}
        out = []

        def add(name, expect, trust="trusted", digest=d):
            res = infra_provider.resolve(self.root, request(digest=digest, trust=trust))
            data = res["profile_bytes"]
            out.append(
                {
                    "name": name,
                    "expect": expect,
                    "pin": pin,
                    "repo": f"{OWNER}/app",
                    "trust": trust,
                    "result": res["result"],
                    "profile": data.hex() if data is not None else None,
                }
            )

        add("resolved", "resolved")
        add("public default", "hosted-only", trust="untrusted")
        add("another digest than the index names", "unavailable", digest="sha256:" + "1" * 64)
        write_policy(self.root, revision=2, withdrawn={"runner_classes": [], "credentials": ["deploy"]})
        add("narrowed by the current policy", "resolved")
        write_policy(self.root, revision=3, revoked_releases=[{"version": VERSION}])
        add("revoked", "unavailable")
        write_policy(self.root, revision=4, repositories_enabled=[])
        add("not enabled", "unavailable")
        (self.root / infra_provider.POLICY).unlink()
        add("no policy", "unavailable")
        return out

    def test_every_released_engine_judges_the_provider_as_this_one_does(self):
        cases = self.cases()
        here = []
        for c in cases:
            pin = InfraPin(**c["pin"])
            data = bytes.fromhex(c["profile"]) if c["profile"] else None
            r = infra.evaluate(
                pin, infra.request_for(pin, repo=c["repo"], event_trust=c["trust"]), c["result"], data
            )
            here.append(r.status)
        self.assertEqual(here, [c["expect"] for c in cases])
        f = tmpdir(self) / "cases.json"
        f.write_text(json.dumps(cases))
        for tag in RELEASES:
            src = _extract(tag, tmpdir(self))
            p = subprocess.run(
                [sys.executable, "-c", DRIVER, str(src), str(f)],
                capture_output=True,
                text=True,
                env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            )
            self.assertEqual(p.returncode, 0, f"{tag}: {p.stderr}")
            got = json.loads(p.stdout)
            self.assertEqual([g["status"] for g in got], [c["expect"] for c in cases], tag)
            for g, c in zip(got, cases):
                self.assertEqual(g["pin_errors"], [], tag)
                if c["profile"]:
                    self.assertEqual(g["profile_problems"], [], f"{tag} {c['name']}")

    def test_a_pin_without_a_digest_kind_means_the_same_in_every_release(self):
        pin = {"provider": "example-infra", "config_release": VERSION, "config_digest": "sha256:" + "a" * 64}
        errs = []
        self.assertIsNone(parse_pin(pin, errs).config_digest_kind)
        f = tmpdir(self) / "cases.json"
        f.write_text(json.dumps([]))
        for tag in RELEASES:
            src = _extract(tag, tmpdir(self))
            code = (
                "import sys,json; sys.path.insert(0, sys.argv[1]); from dev_platform.config import parse_pin; "
                "e=[]; p=parse_pin(json.loads(sys.argv[2]), e); print(json.dumps([p.config_release, p.config_digest, e]))"
            )
            p = subprocess.run(
                [sys.executable, "-c", code, str(src), json.dumps(pin)], capture_output=True, text=True
            )
            self.assertEqual(json.loads(p.stdout), [VERSION, pin["config_digest"], []], tag)


if __name__ == "__main__":
    unittest.main()
