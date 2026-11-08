"""Tests for logging level normalization and configuration."""

import pytest

from episodic import logging as episodic_logging


@pytest.mark.parametrize(
    ("requested_level", "expected_level", "expected_used_default"),
    [
        (None, episodic_logging.LogLevel.INFO, True),
        ("", episodic_logging.LogLevel.INFO, True),
        ("debug", episodic_logging.LogLevel.DEBUG, False),
        ("warning", episodic_logging.LogLevel.WARNING, False),
        ("warn", episodic_logging.LogLevel.WARNING, False),
        ("WARN", episodic_logging.LogLevel.WARNING, False),
        ("invalid", episodic_logging.LogLevel.INFO, True),
    ],
)
def test_configure_logging_normalizes_levels(
    monkeypatch: pytest.MonkeyPatch,
    requested_level: str | None,
    expected_level: episodic_logging.LogLevel,
    expected_used_default: object,
) -> None:
    """configure_logging should normalize levels before delegating to femtologging."""
    recorded_calls: list[tuple[str, bool]] = []

    def _fake_basic_config(*, level: str, force: bool) -> None:
        """Record the level and force flag passed to basicConfig."""
        recorded_calls.append((level, force))

    monkeypatch.setattr(episodic_logging, "basicConfig", _fake_basic_config)

    if (requested_level or "").upper() == "WARN":
        with pytest.warns(DeprecationWarning, match="LogLevel.WARN is deprecated"):
            effective_level, used_default = episodic_logging.configure_logging(
                requested_level,
                force=True,
            )
    else:
        effective_level, used_default = episodic_logging.configure_logging(
            requested_level,
            force=True,
        )

    assert (effective_level, used_default) == (
        expected_level,
        expected_used_default,
    ), "configure_logging must return the normalized level and default flag"
    assert recorded_calls == [(expected_level, True)], (
        "configure_logging must delegate the normalized level with force=True"
    )


def test_configure_logging_uses_false_as_default_force_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_logging should forward `force=False` when omitted."""
    recorded_calls: list[tuple[str, bool]] = []

    def _fake_basic_config(*, level: str, force: bool) -> None:
        """Record the level and force flag passed to basicConfig."""
        recorded_calls.append((level, force))

    monkeypatch.setattr(episodic_logging, "basicConfig", _fake_basic_config)
    effective_level, used_default = episodic_logging.configure_logging("debug")

    assert (effective_level, used_default) == (
        episodic_logging.LogLevel.DEBUG,
        False,
    ), "configure_logging must return DEBUG with a non-default level marker"
    assert recorded_calls == [(episodic_logging.LogLevel.DEBUG, False)], (
        "configure_logging must delegate force=False when force is omitted"
    )
