"""Configure imports for duplication-gate script tests."""

import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1]
# Put the gate's own directory ahead of the rest of `sys.path`. These tests
# exist to exercise the in-tree gate modules, so an installed distribution of
# the same name must not shadow them; appending would let it win.
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
