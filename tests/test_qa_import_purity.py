"""Import-purity checks for QA evaluator contracts.

A worker or storage adapter that maps an evaluator result must not pay for the
LangGraph orchestration stack or an HTTP client. Python executes a package's
``__init__`` on any submodule import, so a single re-export in the
``episodic.qa`` barrel is enough to pull both in. Each case here imports the
module in a fresh interpreter, because this process has already loaded
dependencies for other tests and would mask a newly reintroduced re-export.
"""

import importlib.util
import json
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # Runs a probe interpreter with static arguments.
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import importlib
import json
import sys

importlib.import_module(sys.argv[1])
print(json.dumps({
    "langgraph": "langgraph" in sys.modules,
    "httpx": "httpx" in sys.modules,
}))
"""

# Modules that must stay importable without orchestration or network support.
_PURE_MODULES = ("episodic.qa.pedante.types",)


def _run_probe(module_name: str) -> dict[str, bool]:
    """Import *module_name* in a fresh interpreter and report loaded deps."""
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # shell=False with static arguments.
        [sys.executable, "-c", _PROBE, module_name],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == 0, (
        f"probe failed to import {module_name!r}:\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize("module_name", _PURE_MODULES)
def test_evaluator_contract_import_is_pure(module_name: str) -> None:
    """Importing an evaluator contract loads neither LangGraph nor httpx."""
    assert importlib.util.find_spec(module_name) is not None, (
        f"{module_name!r} must exist for its purity guarantee to mean anything"
    )

    loaded = _run_probe(module_name)

    assert loaded == {"langgraph": False, "httpx": False}, (
        f"importing {module_name!r} must not load the orchestration stack or an "
        f"HTTP client; got {loaded!r}"
    )


def test_probe_detects_langgraph_when_present() -> None:
    """Negative control: the probe reports a dependency that really is loaded."""
    loaded = _run_probe("episodic.qa.langgraph")

    assert loaded["langgraph"] is True, (
        "the probe must observe langgraph when the imported module uses it, "
        "otherwise the purity assertions above are vacuous"
    )
