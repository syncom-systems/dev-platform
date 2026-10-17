import sys
import unittest


class Ok(unittest.TestCase):
    def test_interpreter(self):
        self.assertGreaterEqual(sys.version_info[:2], (3, 11))
