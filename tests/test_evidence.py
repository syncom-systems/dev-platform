import json
import stat
import unittest

from dev_platform import evidence
from dev_platform.errors import ConfigError
from dev_platform.records import canonical_digest
from tests.helpers import tmpdir

DOC = {"schema": "dev-platform.result/v1", "revision": "a" * 40}


class EvidenceStore(unittest.TestCase):
    def test_put_get_roundtrip_and_idempotent(self):
        s = tmpdir(self)
        d = evidence.put(s, DOC)
        self.assertEqual(d, canonical_digest(DOC))
        self.assertEqual(evidence.put(s, DOC), d)
        self.assertEqual(evidence.get(s, d), DOC)

    def test_files_are_read_only(self):
        s = tmpdir(self)
        d = evidence.put(s, DOC)
        mode = (s / d[:2] / f"{d}.json").stat().st_mode
        self.assertFalse(mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    def test_tampering_is_detected_on_get_scan_and_put(self):
        s = tmpdir(self)
        d = evidence.put(s, DOC)
        p = s / d[:2] / f"{d}.json"
        p.chmod(0o600)
        p.write_text(json.dumps({**DOC, "revision": "b" * 40}))
        with self.assertRaises(ConfigError):
            evidence.get(s, d)
        with self.assertRaises(ConfigError):
            evidence.put(s, DOC)
        good, bad = evidence.scan(s)
        self.assertEqual((good, len(bad)), ({}, 1))

    def test_missing_digest(self):
        with self.assertRaises(ConfigError):
            evidence.get(tmpdir(self), "0" * 64)


if __name__ == "__main__":
    unittest.main()
