"""Tests for the Alembic database-URL resolution used by ``alembic/env.py``.

``alembic/env.py`` dispatches a migration run at import time, so its
``_configure_database_url`` helper delegates to
``episodic.canonical.storage.alembic_helpers.configure_database_url``. These
tests exercise that seam through the project's Alembic configuration isolation
pattern without executing any migration.
"""

import pytest

from episodic.canonical.storage.alembic_helpers import (
    alembic_config,
    configure_database_url,
)

_ENVIRONMENT_URL = "postgresql+asyncpg://env-user@env-host/env-db"
_CONFIGURED_URL = "postgresql+asyncpg://cfg-user@cfg-host/cfg-db"


def test_configure_database_url_prefers_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DATABASE_URL`` must override any URL already present in the config."""
    monkeypatch.setenv("DATABASE_URL", _ENVIRONMENT_URL)
    cfg = alembic_config(_CONFIGURED_URL)

    configure_database_url(cfg)

    assert cfg.get_main_option("sqlalchemy.url") == _ENVIRONMENT_URL, (
        "DATABASE_URL must take precedence over the configured sqlalchemy.url"
    )


def test_configure_database_url_retains_the_configured_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing non-empty ``sqlalchemy.url`` survives an absent environment."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    cfg = alembic_config(_CONFIGURED_URL)

    configure_database_url(cfg)

    assert cfg.get_main_option("sqlalchemy.url") == _CONFIGURED_URL, (
        "the configured sqlalchemy.url must be preserved when DATABASE_URL is unset"
    )


def test_configure_database_url_rejects_missing_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject configurations with neither ``DATABASE_URL`` nor a config URL."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    cfg = alembic_config("")

    with pytest.raises(ValueError, match="DATABASE_URL") as excinfo:
        configure_database_url(cfg)

    assert str(excinfo.value) == (
        "DATABASE_URL is not set and sqlalchemy.url is empty."
    ), "the failure must name both resolution sources it exhausted"
