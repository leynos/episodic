"""Tests for the code-duplication gate helper script.

The gate depends on PyChase, which imports removed ``ast`` aliases on
Python 3.14, so the whole module is skipped when that import fails; the
``make duplication-test`` target runs these tests on Python 3.13.
"""

import re
import textwrap
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path

try:
    import duplication_gate as gate
except ImportError:  # pragma: no cover - Python 3.14 path
    pytest.skip(
        "duplication_gate requires PyChase, which needs Python < 3.14",
        allow_module_level=True,
    )
except AttributeError as error:  # pragma: no cover - Python 3.14 path
    if str(error) != "module 'ast' has no attribute 'Str'":
        raise
    pytest.skip(
        "duplication_gate requires PyChase, which needs Python < 3.14",
        allow_module_level=True,
    )


def _finding(
    first: str = "episodic/a.py::alpha",
    second: str = "episodic/b.py::beta",
    score: float = 1.0,
) -> gate.Finding:
    """Build a finding with derived locations for partitioning tests."""
    return gate.Finding(
        first=first,
        second=second,
        location_first=f"{first.split('::')[0]}:1-20",
        location_second=f"{second.split('::')[0]}:1-20",
        score=score,
    )


class TestAllowEntry:
    """Matching semantics for unit and pair allow entries."""

    def test_unit_entry_matches_either_side(self) -> None:
        """A unit entry silences any pair the unit participates in."""
        entry = gate.AllowEntry(units=("episodic/a.py::alpha",), reason="r")
        assert entry.matches("episodic/a.py::alpha", "episodic/b.py::beta"), (
            "Unit entry must match its left member."
        )
        assert entry.matches("episodic/b.py::beta", "episodic/a.py::alpha"), (
            "Unit entry must match its right member."
        )
        assert not entry.matches("episodic/b.py::beta", "episodic/c.py::gamma"), (
            "Unit entry must not match unrelated members."
        )

    def test_pair_entry_matches_unordered(self) -> None:
        """A pair entry silences only that unordered pair."""
        entry = gate.AllowEntry(
            units=("episodic/a.py::alpha", "episodic/b.py::beta"),
            reason="r",
        )
        assert entry.matches("episodic/b.py::beta", "episodic/a.py::alpha"), (
            "Pair entry must ignore member order."
        )
        assert not entry.matches("episodic/a.py::alpha", "episodic/c.py::gamma"), (
            "Pair entry must not match a different pair."
        )


class TestNormalizeFindings:
    """Normalization of raw PyChase pair payloads."""

    def test_orders_by_descending_score_then_location(self) -> None:
        """Findings sort by score, then by source location."""
        raw: list[gate._DetectorPairPayload] = [
            {
                "score": 0.9,
                "left": {
                    "file": "episodic/z.py",
                    "start_line": 1,
                    "end_line": 20,
                    "qualname": "one",
                },
                "right": {
                    "file": "episodic/z.py",
                    "start_line": 30,
                    "end_line": 50,
                    "qualname": "two",
                },
            },
            {
                "score": 1.0,
                "left": {
                    "file": "episodic/a.py",
                    "start_line": 5,
                    "end_line": 25,
                    "qualname": "three",
                },
                "right": {
                    "file": "episodic/b.py",
                    "start_line": 5,
                    "end_line": 25,
                    "qualname": "four",
                },
            },
        ]
        findings = gate.normalize_findings(raw)
        assert [f.score for f in findings] == [1.0, 0.9], (
            "Findings must descend by similarity."
        )
        assert findings[0].first == "episodic/a.py::three", (
            "Higher-scored finding must sort first."
        )
        assert findings[0].location_first == "episodic/a.py:5-25", (
            "Normalized location must retain source lines."
        )


class TestDetectorMember:
    """PyChase member payload validation."""

    _VALID_PAYLOAD: typ.ClassVar[dict[str, object]] = {
        "file": "episodic/a.py",
        "qualname": "module.function",
        "start_line": 10,
        "end_line": 20,
    }
    _MISSING = object()

    def test_accepts_a_valid_payload(self) -> None:
        """A complete PyChase member retains its original field values."""
        assert (
            gate._detector_member(self._VALID_PAYLOAD, context="member")
            == self._VALID_PAYLOAD
        ), "Valid PyChase member payloads must round-trip."

    @pytest.mark.parametrize(
        ("field", "invalid_value", "expected_error", "message"),
        [
            (
                "file",
                _MISSING,
                ValueError,
                "member.file must be a non-empty string",
            ),
            ("file", "", ValueError, "member.file must be a non-empty string"),
            (
                "file",
                1,
                ValueError,
                "member.file must be a non-empty string",
            ),
            (
                "qualname",
                _MISSING,
                ValueError,
                "member.qualname must be a non-empty string",
            ),
            (
                "qualname",
                "",
                ValueError,
                "member.qualname must be a non-empty string",
            ),
            (
                "qualname",
                1,
                ValueError,
                "member.qualname must be a non-empty string",
            ),
            (
                "start_line",
                True,
                TypeError,
                "member.start_line must be a positive integer",
            ),
            (
                "start_line",
                "10",
                TypeError,
                "member.start_line must be a positive integer",
            ),
            (
                "end_line",
                False,
                TypeError,
                "member.end_line must not precede start_line",
            ),
            (
                "start_line",
                0,
                ValueError,
                "member.start_line must be a positive integer",
            ),
            (
                "start_line",
                -1,
                ValueError,
                "member.start_line must be a positive integer",
            ),
            (
                "end_line",
                "20",
                TypeError,
                "member.end_line must not precede start_line",
            ),
            (
                "end_line",
                _MISSING,
                TypeError,
                "member.end_line must not precede start_line",
            ),
            ("end_line", 9, ValueError, "member.end_line must not precede start_line"),
        ],
        ids=[
            "missing-file",
            "empty-file",
            "non-string-file",
            "missing-qualname",
            "empty-qualname",
            "non-string-qualname",
            "boolean-start-line",
            "non-integer-start-line",
            "boolean-end-line",
            "zero-start-line",
            "negative-start-line",
            "non-integer-end-line",
            "missing-end-line",
            "inverted-lines",
        ],
    )
    def test_rejects_invalid_field_values(
        self,
        field: str,
        invalid_value: object,
        expected_error: type[Exception],
        message: str,
    ) -> None:
        """Invalid fields preserve PyChase's exception types and messages."""
        payload: dict[str, object] = self._VALID_PAYLOAD.copy()
        if invalid_value is self._MISSING:
            del payload[field]
        else:
            payload[field] = invalid_value
        with pytest.raises(expected_error) as error:
            gate._detector_member(payload, context="member")
        assert type(error.value) is expected_error, "Exception type must remain exact."
        assert str(error.value) == message, "Validation message must remain exact."

    def test_rejects_non_mapping_payload(self) -> None:
        """Non-object PyChase members fail at the detector boundary."""
        with pytest.raises(
            TypeError,
            match=re.escape("member must be an object with string keys"),
        ):
            gate._detector_member([], context="member")


class TestLoadAllowlist:
    """Allowlist parsing and validation."""

    def _write(self, tmp_path: object, body: str) -> object:
        """Write ``body`` to ``pyproject.toml`` under ``tmp_path`` and return it."""
        pyproject = typ.cast("Path", tmp_path) / "pyproject.toml"
        pyproject.write_text(textwrap.dedent(body), encoding="utf-8")
        return pyproject

    def test_loads_unit_and_pair_entries(self, tmp_path: object) -> None:
        """Unit and pair entries load with their reasons."""
        pyproject = typ.cast(
            "Path",
            self._write(
                tmp_path,
                """\
            [[tool.duplication_gate.allow]]
            unit = "episodic/a.py::alpha"
            reason = "declarative"

            [[tool.duplication_gate.allow]]
            pair = ["episodic/b.py::beta", "episodic/c.py::gamma"]
            reason = "parallel contracts"
            """,
            ),
        )
        entries = gate.load_allowlist(pyproject)
        assert entries[0].units == ("episodic/a.py::alpha",), (
            "Unit entry must retain its target."
        )
        assert entries[1].units == ("episodic/b.py::beta", "episodic/c.py::gamma"), (
            "Pair entry must retain both targets."
        )
        assert entries[1].reason == "parallel contracts", (
            "Allow entry must retain its reason."
        )

    def test_missing_gate_table_yields_empty_allowlist(self, tmp_path: object) -> None:
        """A pyproject without the gate table produces no entries."""
        pyproject = typ.cast(
            "Path",
            self._write(tmp_path, "[project]\nname = 'x'\nversion = '0'\n"),
        )
        assert gate.load_allowlist(pyproject) == (), (
            "Missing gate table must mean no allow entries."
        )

    @pytest.mark.parametrize(
        ("body", "diagnostic"),
        [
            (
                '[[tool.duplication_gate.allow]]\nunit = "episodic/a.py::alpha"\n',
                "requires a non-empty reason",
            ),
            (
                '[[tool.duplication_gate.allow]]\nunit = "a"\nreason = "r"\n',
                "unit must be a 'path::qualname' string",
            ),
            (
                '[[tool.duplication_gate.allow]]\npair = ["a.py::x"]\nreason = "r"\n',
                "pair must be two 'path::qualname' strings",
            ),
            (
                '[[tool.duplication_gate.allow]]\nreason = "r"\n',
                "must set exactly one of 'unit' or 'pair'",
            ),
            (
                (
                    '[[tool.duplication_gate.allow]]\nunit = "episodic/a.py::x"\n'
                    'pair = ["episodic/a.py::x", "episodic/b.py::y"]\nreason = "r"\n'
                ),
                "must set exactly one of 'unit' or 'pair'",
            ),
        ],
        ids=[
            "no-reason",
            "malformed-unit",
            "one-member-pair",
            "no-target",
            "both-kinds",
        ],
    )
    def test_rejects_malformed_entries(
        self,
        tmp_path: object,
        body: str,
        diagnostic: str,
    ) -> None:
        """Malformed entries raise a configuration error."""
        pyproject = typ.cast("Path", self._write(tmp_path, body))
        with pytest.raises(gate.GateConfigError, match=re.escape(diagnostic)):
            gate.load_allowlist(pyproject)


class TestPartitionFindings:
    """Blocking, allowed, and stale-entry partitioning."""

    def test_unmatched_findings_block(self) -> None:
        """A finding with no matching entry blocks the gate."""
        blocking, allowed, stale = gate.partition_findings([_finding()], [])
        assert len(blocking) == 1, "Unmatched finding must block."
        assert not allowed, "Unmatched finding must not be allowed."
        assert not stale, "Empty allowlist must not yield stale entries."

    def test_matched_findings_are_allowed(self) -> None:
        """Entries silence their findings and are not reported stale."""
        entry = gate.AllowEntry(units=("episodic/a.py::alpha",), reason="r")
        blocking, allowed, stale = gate.partition_findings([_finding()], [entry])
        assert not blocking, "Matching entry must prevent blocking."
        assert len(allowed) == 1, "Matching entry must allow the finding."
        assert not stale, "Used entry must not be stale."

    def test_unused_entries_are_stale(self) -> None:
        """Entries matching nothing are reported for removal."""
        entry = gate.AllowEntry(units=("episodic/gone.py::old",), reason="r")
        blocking, _allowed, stale = gate.partition_findings([_finding()], [entry])
        assert len(blocking) == 1, "Unmatched finding must remain blocking."
        assert stale == [entry], "Unused allow entry must be stale."
