"""Tests of lib."""

from pylib.lib import add


def test_add() -> None:
    """Two and three make five."""
    assert add(2, 3) == 5
