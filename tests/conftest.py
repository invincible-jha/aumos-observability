"""Shared fixtures and path setup for aumos-observability tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the src directory is on the Python path when tests are run without
# the package being installed in editable mode.
_repo_root = Path(__file__).parent.parent
_src_path = str(_repo_root / "src")
_common_src_path = str(_repo_root.parent / "aumos-common" / "src")

for _path in (_src_path, _common_src_path):
    if _path not in sys.path:
        sys.path.insert(0, _path)
