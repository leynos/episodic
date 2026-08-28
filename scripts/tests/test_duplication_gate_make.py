"""Make-target contract tests for recording duplication exceptions."""

import dataclasses as dc
import shutil
import subprocess  # noqa: S404 - tests exercise the real Make target.
import sys
import typing as typ
from pathlib import Path

import pytest
from duplication_gate_test_support import (
    REPOSITORY_ROOT,
    allowlist,
    copied_gate_workspace,
    gate_environment,
)


@dc.dataclass(frozen=True, slots=True)
class _MakeAllowRequest:
    """The `FIRST`, `SECOND`, and `REASON` inputs for one Make target run."""

    first: str | None
    second: str | None
    reason: str | None


def _make_allow(
    workspace: object,
    *,
    request: _MakeAllowRequest,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real Make target against a copied, writable gate workspace."""
    make = shutil.which("make")
    assert make is not None, "Expected make to be available for contract tests."
    command = [
        make,
        "--no-print-directory",
        "-f",
        str(REPOSITORY_ROOT / "Makefile"),
        "duplication-allow",
        f"DUPLICATION_GATE={sys.executable} scripts/duplication_gate.py",
    ]
    if request.first is not None:
        command.append(f"FIRST={request.first}")
    if request.second is not None:
        command.append(f"SECOND={request.second}")
    if request.reason is not None:
        command.append(f"REASON={request.reason}")
    workspace_path = Path(typ.cast("Path", workspace))
    return subprocess.run(  # noqa: S603 - fixed Make target and copied workspace.
        command,
        cwd=workspace_path,
        env=gate_environment() if environment is None else environment,
        check=False,
        capture_output=True,
        text=True,
    )


class TestMakeDuplicationAllow:
    """The `make duplication-allow` command-line contract."""

    @pytest.mark.parametrize(
        ("first", "reason", "expected_error"),
        [
            pytest.param(None, "reviewed exception", "FIRST is required", id="first"),
            pytest.param("episodic/a.py", None, "REASON is required", id="reason"),
        ],
    )
    def test_make_duplication_allow_rejects_missing_and_ambient_values(
        self,
        tmp_path: object,
        first: str | None,
        reason: str | None,
        expected_error: str,
    ) -> None:
        """Only command-line values satisfy the Make target's required inputs."""
        workspace, _script = copied_gate_workspace(typ.cast("Path", tmp_path))
        environment = {
            **gate_environment(),
            "FIRST": "episodic/ambient.py",
            "SECOND": "episodic/ambient_second.py",
            "REASON": "ambient reason",
        }
        result = _make_allow(
            workspace,
            request=_MakeAllowRequest(first=first, second=None, reason=reason),
            environment=environment,
        )
        assert result.returncode == 2, result.stderr
        assert expected_error in result.stderr, (
            "Make must reject ambient values for required arguments."
        )

    @pytest.mark.parametrize(
        ("second", "expected_keys"),
        [
            pytest.param(None, ("episodic/a.py",), id="unit"),
            pytest.param(
                "episodic/b.py::beta",
                ("episodic/a.py", "episodic/b.py::beta"),
                id="members",
            ),
        ],
    )
    def test_make_duplication_allow_round_trips_quoted_values(
        self,
        tmp_path: object,
        second: str | None,
        expected_keys: tuple[str, ...],
    ) -> None:
        """The Make target forwards unit and member inputs as literal arguments."""
        workspace, _script = copied_gate_workspace(typ.cast("Path", tmp_path))
        marker = typ.cast("Path", tmp_path) / "injected-command"
        reason = f'kept literally: "$(touch {marker})"; $HOME'
        result = _make_allow(
            workspace,
            request=_MakeAllowRequest(
                first="episodic/a.py", second=second, reason=reason
            ),
        )
        assert result.returncode == 0, result.stderr
        entries = allowlist.load_allowlist(workspace / "pyproject.toml")
        assert entries[0].keys == expected_keys, (
            "Make must forward the requested keys exactly."
        )
        assert entries[0].reason == reason, "Make must preserve quoted reasons."
        assert not marker.exists(), "Quoted values must not execute shell fragments."
