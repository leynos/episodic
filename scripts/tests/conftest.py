"""Configure imports for duplication-gate script tests."""

import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1]
# The directory must be appended, not prepended. Neither `tests/` nor this
# directory carries an `__init__.py`, so `tests` is a PEP 420 namespace package
# spanning both; putting `scripts/` first would make `tests.conftest` resolve to
# this file and break the importers of the root conftest's helpers. Reachability
# of the gate modules is already guaranteed by this entry plus the repository
# root being on `sys.path`.
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.append(str(SCRIPT_DIRECTORY))
