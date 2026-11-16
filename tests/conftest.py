"""Make the plugin modules, the test helpers and the Hermes source importable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../tests
REPO_ROOT = HERE.parent                          # plugin repo root

for candidate in (str(REPO_ROOT), str(HERE), os.environ.get("HERMES_SRC", "")):
    if candidate and candidate not in sys.path:
        sys.path.insert(0, candidate)
