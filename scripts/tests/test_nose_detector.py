"""Tests for the pinned nose detector wrapper used by the duplication gate."""

import copy
import dataclasses as dc
import re
import textwrap
import typing as typ

import pytest
from duplication_gate_test_support import (
    STUB_REPORT,
    detector,
    stub_runner,
    stub_settings,
    write_stub_nose,
)

if typ.TYPE_CHECKING:
    from collections import abc as cabc
    from pathlib import Path


def _settings_body(
    *,
    version: str | None = '"0.20.0"',
    roots: str = '["episodic"]',
    min_size: str = "24",
    surface: str | None = None,
) -> str:
    """Build a `[tool.nose]` table body from the supplied literal values."""
    lines = ["[tool.nose]"]
    if version is not None:
        lines.append(f"version = {version}")
    lines.extend((f"roots = {roots}", 'mode = "syntax"', f"min-size = {min_size}"))
    if surface is not None:
        lines.append(f"surface = {surface}")
    return "\n".join(lines) + "\n"


class TestLoadSettings:
    """`[tool.nose]` settings parsing."""

    def _write(self, tmp_path: Path, body: str) -> Path:
        """Write ``body`` to ``pyproject.toml`` under ``tmp_path``."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(textwrap.dedent(body), encoding="utf-8")
        return pyproject

    def test_loads_the_repository_settings(self, tmp_path: Path) -> None:
        """A complete table produces validated settings."""
        pyproject = self._write(
            tmp_path,
            """\
            [tool.nose]
            version = "0.20.0"
            roots = ["episodic"]
            mode = "syntax"
            min-size = 24
            surface = "all"
            top = 30
            exclude = ["**/generated/**"]
            """,
        )
        settings = detector.load_settings(pyproject)
        assert settings.roots == ("episodic",), "Roots must round-trip in order."
        assert settings.exclude == ("**/generated/**",), (
            "Exclude globs must round-trip."
        )
        assert settings.top == 30, "The ranking bound must round-trip."

    def test_top_and_exclude_are_optional(self, tmp_path: Path) -> None:
        """Omitted optional keys fall back to nose's own view size."""
        pyproject = self._write(
            tmp_path,
            """\
            [tool.nose]
            version = "0.20.0"
            roots = ["episodic"]
            mode = "syntax"
            min-size = 24
            """,
        )
        settings = detector.load_settings(pyproject)
        assert settings.top is None, "An omitted `top` must not bound the view."
        assert settings.surface == "all", "The gate defaults to the widened surface."

    @pytest.mark.parametrize(
        ("body", "diagnostic"),
        [
            (
                _settings_body(version=None),
                "tool.nose.version must be a non-empty string",
            ),
            (
                _settings_body(roots='"episodic"'),
                "tool.nose.roots must be an array of strings",
            ),
            (
                _settings_body(min_size="0"),
                "tool.nose.min-size must be a positive integer",
            ),
            (
                _settings_body(surface='"everything"'),
                "tool.nose.surface must be 'default' or 'all'",
            ),
        ],
        ids=["missing-version", "string-roots", "zero-min-size", "bad-surface"],
    )
    def test_rejects_malformed_settings(
        self, tmp_path: Path, body: str, diagnostic: str
    ) -> None:
        """Malformed settings raise a configuration error."""
        pyproject = self._write(tmp_path, body)
        with pytest.raises(detector.GateConfigError, match=re.escape(diagnostic)):
            detector.load_settings(pyproject)


class TestResolveBinary:
    """Discovery and version verification of the pinned binary."""

    def test_accepts_the_pinned_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A binary reporting the pinned version is accepted."""
        stub = write_stub_nose(tmp_path)
        monkeypatch.setenv("NOSE_BIN", str(stub))
        assert detector.resolve_binary(stub_settings(), runner=stub_runner()) == str(
            stub
        ), "The pinned binary must be returned unchanged."

    def test_rejects_a_version_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A different installed version fails with a remediation hint."""
        stub = write_stub_nose(tmp_path, version="nose 0.19.0")
        monkeypatch.setenv("NOSE_BIN", str(stub))
        with pytest.raises(
            detector.GateExecutionError,
            match=r"reports 'nose 0\.19\.0'.*make install-nose",
        ):
            detector.resolve_binary(
                stub_settings(), runner=stub_runner(version="nose 0.19.0")
            )

    def test_reports_a_missing_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing detector fails with the install remediation."""
        monkeypatch.delenv("NOSE_BIN", raising=False)
        monkeypatch.setattr(detector, "_discover_binary", lambda: None)
        with pytest.raises(detector.GateExecutionError, match="make install-nose"):
            detector.resolve_binary(stub_settings(), runner=stub_runner())


class TestBuildCommand:
    """Translation of gate settings into a nose query command."""

    def test_pins_every_configured_setting(self) -> None:
        """Roots, surface, ranking bound, channels, and size are all passed."""
        command = detector.build_command(
            "nose",
            dc.replace(stub_settings(), roots=("episodic", "openai_test_types.py")),
        )
        assert command[:6] == [
            "nose",
            "query",
            "--root",
            "episodic",
            "--root",
            "openai_test_types.py",
        ], "Every configured root must be passed with --root."
        assert "all" in command, "The widened surface must pass the `all` term."
        assert "top=30" in command, "The ranking bound must be passed as a term."
        assert command[-2:] == ["--format", "json"], "The gate must parse JSON."

    def test_default_surface_omits_the_all_term(self) -> None:
        """The default surface leaves nose on its ranked dashboard."""
        command = detector.build_command(
            "nose", dc.replace(stub_settings(), surface="default", top=None)
        )
        assert "all" not in command, "The default surface must not widen the view."
        assert not any(item.startswith("top=") for item in command), (
            "An unset ranking bound must not be passed."
        )


class TestRunDetector:
    """Report parsing and finding normalization."""

    def test_normalizes_a_stub_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A stub report becomes one ordered finding with both locations."""
        monkeypatch.setenv("NOSE_BIN", "/stub/nose")
        findings = detector.run_detector(stub_settings(), runner=stub_runner())
        assert len(findings) == 1, "The stub report contains one family."
        assert findings[0].label == "episodic/a.py:1-20 ~ episodic/b.py:30-49", (
            "Findings must report both spans."
        )

    def test_orders_by_descending_value_then_location(self) -> None:
        """Findings sort by value, then by their location labels."""
        report = {
            "families": [
                {
                    "witness": "copy-paste",
                    "value": 5.0,
                    "locations": [
                        {"file": "episodic/z.py", "start": 1, "end": 2, "name": None},
                        {"file": "episodic/y.py", "start": 1, "end": 2, "name": None},
                    ],
                },
                {
                    "witness": "exact",
                    "value": 9.0,
                    "locations": [
                        {"file": "episodic/a.py", "start": 1, "end": 2, "name": "run"},
                        {"file": "episodic/b.py", "start": 1, "end": 2, "name": "run"},
                    ],
                },
            ]
        }
        findings = detector.normalize_findings(report)
        assert [finding.value for finding in findings] == [9.0, 5.0], (
            "Higher-value families must sort first."
        )
        assert findings[0].label == ("episodic/a.py:1-2 run ~ episodic/b.py:1-2 run"), (
            "Named locations must carry their unit name into the report."
        )

    def test_orders_equal_values_by_location_label(self) -> None:
        """Equal-value families sort lexicographically by their location labels."""
        report = {
            "families": [
                {
                    "witness": "copy-paste",
                    "value": 5.0,
                    "locations": [
                        {"file": "episodic/z.py", "start": 1, "end": 2, "name": None},
                        {"file": "episodic/y.py", "start": 1, "end": 2, "name": None},
                    ],
                },
                {
                    "witness": "copy-paste",
                    "value": 5.0,
                    "locations": [
                        {"file": "episodic/b.py", "start": 1, "end": 2, "name": None},
                        {"file": "episodic/a.py", "start": 1, "end": 2, "name": None},
                    ],
                },
            ]
        }

        findings = detector.normalize_findings(report)

        assert [finding.label for finding in findings] == [
            "episodic/b.py:1-2 ~ episodic/a.py:1-2",
            "episodic/z.py:1-2 ~ episodic/y.py:1-2",
        ], "Equal values must order by normalized location label."

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(7, 7.0, id="integer"),
            pytest.param(7.5, 7.5, id="float"),
        ],
    )
    def test_normalizes_numeric_values_to_float(
        self,
        value: float,
        expected: float,
    ) -> None:
        """Integer and floating-point family values both normalize to float."""
        report = copy.deepcopy(STUB_REPORT)
        typ.cast("dict[str, typ.Any]", report)["families"][0]["value"] = value
        findings = detector.normalize_findings(report)
        assert isinstance(findings[0].value, float), (
            "Normalization must coerce family values to float."
        )
        assert findings[0].value == expected, "Normalization must preserve the value."

    @pytest.mark.parametrize(
        ("mutate", "diagnostic"),
        [
            pytest.param(
                lambda report: report.__setitem__("families", {}),
                "families must be an array",
                id="families-object",
            ),
            pytest.param(
                lambda report: report["families"][0].__setitem__("value", "high"),
                "value must be a number",
                id="string-value",
            ),
            pytest.param(
                lambda report: report["families"][0].update({"value": True}),
                "value must be a number",
                id="boolean-value",
            ),
            pytest.param(
                lambda report: report["families"][0].pop("value"),
                "value must be a number",
                id="missing-value",
            ),
            pytest.param(
                lambda report: report["families"][0].__setitem__(
                    "locations", "episodic/a.py"
                ),
                "locations must be an array",
                id="string-locations",
            ),
            pytest.param(
                lambda report: report["families"][0].__setitem__(
                    "locations", b"episodic/a.py"
                ),
                "locations must be an array",
                id="bytes-locations",
            ),
            pytest.param(
                lambda report: report["families"][0].__setitem__("locations", []),
                "locations must not be empty",
                id="empty-locations",
            ),
            pytest.param(
                lambda report: report["families"][0]["locations"].__setitem__(
                    0, "episodic/a.py"
                ),
                "families[0].locations[0] must be a table",
                id="malformed-first-location",
            ),
            pytest.param(
                lambda report: report["families"][0]["locations"][0].__setitem__(
                    "start", 0
                ),
                "start must be a positive integer",
                id="zero-start",
            ),
            pytest.param(
                lambda report: report["families"][0]["locations"][0].__setitem__(
                    "end", 0
                ),
                "end must not precede start",
                id="inverted-span",
            ),
            pytest.param(
                lambda report: report["families"][0]["locations"][0].__setitem__(
                    "name", ""
                ),
                "name must be a non-empty string or null",
                id="empty-name",
            ),
        ],
    )
    def test_rejects_malformed_reports(
        self,
        mutate: cabc.Callable[[dict[str, typ.Any]], None],
        diagnostic: str,
    ) -> None:
        """Schema violations fail at the detector boundary."""
        report = copy.deepcopy(STUB_REPORT)
        mutate(typ.cast("dict[str, typ.Any]", report))
        with pytest.raises(detector.GateConfigError, match=re.escape(diagnostic)):
            detector.normalize_findings(report)

    def test_rejects_unreadable_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-JSON detector output fails with an execution error."""
        monkeypatch.setenv("NOSE_BIN", "/stub/nose")

        def runner(command: cabc.Sequence[str]) -> str:
            return "nose 0.20.0\n" if "--version" in command else "not json"

        with pytest.raises(detector.GateExecutionError, match="not valid JSON"):
            detector.run_detector(stub_settings(), runner=runner)


def test_run_command_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow detector becomes an actionable execution error."""

    def timeout(*_args: object, **_kwargs: object) -> typ.NoReturn:
        raise detector.subprocess.TimeoutExpired(["nose", "query"], 120)

    monkeypatch.setattr(detector.subprocess, "run", timeout)

    with pytest.raises(
        detector.GateExecutionError, match="timed out after 120 seconds"
    ):
        detector._run_command(("nose", "query"))
