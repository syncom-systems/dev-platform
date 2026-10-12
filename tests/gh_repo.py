"""The recorded repository double lives in tools/ so the qualification tools can use it too."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "recorded_repo", Path(__file__).resolve().parents[1] / "tools" / "recorded_repo.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
Repo = _mod.Repo
