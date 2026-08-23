"""Command and Make workflow tests for the duplication gate."""

import shutil
import subprocess  # noqa: S404 - tests exercise copied gate and Make commands.
import sys
import textwrap
import typing as typ
from pathlib import Path

import pytest
from duplication_gate_test_support import (
    REPOSITORY_ROOT,
    copied_gate_workspace,
    gate,
    gate_environment,
    run_gate_command,
)


def _finding() -> gate.Finding:
    """Build a representative blocking finding."""
    return gate.Finding(
        first="episodic/a.py::alpha",
        second="episodic/b.py::beta",
        location_first="episodic/a.py:1-20",
        location_second="episodic/b.py:1-20",
        score=1.0,
    )


def _make_allow(
    workspace: object,
    *,
    first: str | None,
    second: str | None,
    reason: str | None,
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
    if first is not None:
        command.append(f"FIRST={first}")
    if second is not None:
        command.append(f"SECOND={second}")
    if reason is not None:
        command.append(f"REASON={reason}")
    workspace_path = Path(typ.cast("Path", workspace))
    return subprocess.run(  # noqa: S603 - fixed Make target and copied workspace.
        command,
        cwd=workspace_path,
        env=gate_environment() if environment is None else environment,
        check=False,
        capture_output=True,
        text=True,
    )


class TestGateCommands:
    """CLI orchestration and real workflow contracts."""

    def test_check_reports_blocking_findings(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The check command emits the blocking report and status one."""
        monkeypatch.chdir(typ.cast("Path", tmp_path))
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())
        monkeypatch.setattr(gate, "run_detector", lambda: [_finding()])
        with pytest.raises(SystemExit) as error:
            gate.check()
        assert error.value.code == 1, "Blocking findings must return status one."
        assert capsys.readouterr().out == (
            "duplicate code: 1 unsuppressed pair(s)\n"
            "  episodic/a.py:1-20 ~ episodic/b.py:1-20 (similarity 1.00)\n"
            "    units: episodic/a.py::alpha ~ episodic/b.py::beta\n"
            "Extract the shared logic into one helper, or record a considered "
            "exception:\n"
            "  make duplication-allow FIRST='<path::qualname>' "
            "[SECOND='<path::qualname>'] REASON='<why this stays>'\n"
        ), "Blocking report must remain actionable and deterministic."

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(OSError("unreadable configuration"), id="allowlist-io"),
            pytest.param(OSError("detector executable unavailable"), id="detector-io"),
            pytest.param(
                RuntimeError("detector runtime failed"), id="detector-runtime"
            ),
        ],
    )
    def test_check_inputs_wrap_environment_failures(self, error: Exception) -> None:
        """Injected reader and detector failures become explicit gate errors."""
        if str(error).startswith("unreadable"):

            def reader(_path: object) -> tuple[gate.AllowEntry, ...]:
                raise error

            def detector() -> list[gate.Finding]:
                return []

        else:

            def reader(_path: object) -> tuple[gate.AllowEntry, ...]:
                return ()

            def detector() -> list[gate.Finding]:
                raise error

        with pytest.raises(gate.GateExecutionError, match=str(error)):
            gate._check_inputs(allowlist_reader=reader, detector=detector)

    def test_check_reports_detector_schema_errors(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed detector reports exit cleanly instead of showing a traceback."""
        monkeypatch.chdir(typ.cast("Path", tmp_path))
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())

        def raise_schema_error() -> list[gate.Finding]:
            msg = "PyChase report pairs must be an array"
            raise TypeError(msg)

        monkeypatch.setattr(gate, "run_detector", raise_schema_error)
        with pytest.raises(SystemExit) as error:
            gate.check()

        assert error.value.code == 2, "Malformed detector reports must return two."
        assert capsys.readouterr().err == (
            "configuration error: PyChase report pairs must be an array\n"
        ), "Schema errors must use the configuration diagnostic."

    def test_allow_reports_malformed_existing_entries(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed existing allows exit cleanly instead of showing a traceback."""
        pyproject = typ.cast("Path", tmp_path) / "pyproject.toml"
        pyproject.write_text(
            '[[tool.duplication_gate.allow]]\nunit = "episodic/a.py::alpha"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)

        with pytest.raises(SystemExit) as error:
            gate.allow(
                first="episodic/b.py::beta",
                reason="reviewed exception",
            )

        assert error.value.code == 2, "Malformed existing allows must return two."
        assert capsys.readouterr().err == (
            "configuration error: duplication_gate.allow[0] "
            "requires a non-empty reason\n"
        ), "Malformed allows must use the configuration diagnostic."

    def test_deterministic_hashing_reexecs_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unpinned process re-execs itself with a deterministic hash seed."""
        calls: list[tuple[str, list[str]]] = []
        environment = dict(gate.os.environ)
        environment.pop("PYTHONHASHSEED", None)
        monkeypatch.setattr(
            gate.os,
            "execv",
            lambda executable, arguments: calls.append((executable, arguments)),
        )
        gate._ensure_deterministic_hashing(environment)
        assert environment["PYTHONHASHSEED"] == "0", "Re-exec must pin the hash seed."
        assert calls == [
            (gate.sys.executable, [gate.sys.executable, *gate.sys.argv])
        ], "Re-exec must retain the current interpreter and arguments."

    @pytest.mark.parametrize(
        ("second", "expected_units"),
        [
            pytest.param(None, ("episodic/a.py::alpha",), id="unit"),
            pytest.param(
                "episodic/b.py::beta",
                ("episodic/a.py::alpha", "episodic/b.py::beta"),
                id="pair",
            ),
        ],
    )
    def test_allow_cli_round_trips_unit_and_pair(
        self,
        tmp_path: object,
        second: str | None,
        expected_units: tuple[str, ...],
    ) -> None:
        """The real allow CLI records both supported exception forms."""
        _workspace, script = copied_gate_workspace(typ.cast("Path", tmp_path))
        arguments = ["allow", "--first", "episodic/a.py::alpha"]
        if second is not None:
            arguments.extend(("--second", second))
        arguments.extend(("--reason", "reviewed exception"))

        result = run_gate_command(script, *arguments)
        assert result.returncode == 0, result.stderr
        entries = gate.load_allowlist(script.parent.parent / "pyproject.toml")
        assert entries[0].units == expected_units, (
            "CLI must retain its requested units."
        )
        assert entries[0].reason == "reviewed exception", (
            "CLI must retain the supplied reason."
        )

    @pytest.mark.parametrize(
        ("first", "reason", "expected_error"),
        [
            pytest.param(None, "reviewed exception", "FIRST is required", id="first"),
            pytest.param(
                "episodic/a.py::alpha", None, "REASON is required", id="reason"
            ),
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
            "FIRST": "episodic/ambient.py::first",
            "SECOND": "episodic/ambient.py::second",
            "REASON": "ambient reason",
        }
        result = _make_allow(
            workspace,
            first=first,
            second=None,
            reason=reason,
            environment=environment,
        )
        assert result.returncode == 2, result.stderr
        assert expected_error in result.stderr, (
            "Make must reject ambient values for required arguments."
        )

    @pytest.mark.parametrize(
        ("second", "expected_units"),
        [
            pytest.param(None, ("episodic/a.py::alpha",), id="unit"),
            pytest.param(
                "episodic/b.py::beta",
                ("episodic/a.py::alpha", "episodic/b.py::beta"),
                id="pair",
            ),
        ],
    )
    def test_make_duplication_allow_round_trips_quoted_values(
        self,
        tmp_path: object,
        second: str | None,
        expected_units: tuple[str, ...],
    ) -> None:
        """The Make target forwards unit and pair inputs as literal arguments."""
        workspace, _script = copied_gate_workspace(typ.cast("Path", tmp_path))
        marker = typ.cast("Path", tmp_path) / "injected-command"
        reason = f'kept literally: "$(touch {marker})"; $HOME'
        result = _make_allow(
            workspace,
            first="episodic/a.py::alpha",
            second=second,
            reason=reason,
        )
        assert result.returncode == 0, result.stderr
        entries = gate.load_allowlist(workspace / "pyproject.toml")
        assert entries[0].units == expected_units, (
            "Make must forward the requested unit or pair exactly."
        )
        assert entries[0].reason == reason, "Make must preserve quoted reasons."
        assert not marker.exists(), "Quoted values must not execute shell fragments."

    def test_real_check_cli_passes(self) -> None:
        """The checked-in gate runs successfully through its real CLI boundary."""
        result = subprocess.run(  # noqa: S603 - fixed repository gate command.
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "duplication_gate.py"),
                "check",
            ],
            cwd=REPOSITORY_ROOT,
            env=gate_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "duplication gate passed" in result.stdout, (
            "Real check invocation must report its successful gate result."
        )

    def test_reports_a_planted_verbatim_copy(self, tmp_path: object) -> None:
        """The pinned engine reports a planted copy through normalization."""
        body = textwrap.dedent(
            """\
            def NAME(items):
                total = 0.0
                for item in items:
                    price = item["price"] * item["quantity"]
                    if item.get("taxable"):
                        price *= 1.2
                    if item.get("discount"):
                        price -= item["discount"]
                    total += price
                if total < 0:
                    total = 0.0
                return round(total, 2)
            """
        )
        module = typ.cast("Path", tmp_path) / "mod.py"
        module.write_text(
            body.replace("NAME", "first_total")
            + "\n\n"
            + body.replace("NAME", "second_total"),
            encoding="utf-8",
        )
        from pychase.cli import (  # ty: ignore[unresolved-import]  # pychase installs only in the gate's Python 3.13 environment.
            Config,
        )
        from pychase.engine import (  # ty: ignore[unresolved-import]  # pychase installs only in the gate's Python 3.13 environment.
            find,
        )

        config = Config()
        config.threshold = 0.9
        config.min_lines = 5
        config.min_nodes = 10
        findings = gate.normalize_findings(find([str(module)], config)["pairs"])
        assert len(findings) == 1, "Planted copy must produce one pair."
        assert findings[0].score == 1.0, "Verbatim copy must have perfect similarity."
