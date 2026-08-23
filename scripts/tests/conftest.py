"""Configure imports for duplication-gate script tests."""

import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.append(str(SCRIPT_DIRECTORY))
