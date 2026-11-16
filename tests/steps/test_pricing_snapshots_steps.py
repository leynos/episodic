"""Behavioural tests for immutable, content-addressed pricing snapshots.

The step definitions live in
`tests.steps.pricing_snapshots_step_definitions`. That module is registered
through `pytest_plugins` in `tests/conftest.py`, because pytest-bdd installs
each step as a fixture in its defining module.
"""

from __future__ import annotations

import pathlib  # ruff: ignore[typing-only-standard-library-import]  # pytest-bdd evaluates step annotations.
import typing as typ

import pytest
from pytest_bdd import scenario
from sqlalchemy.ext.asyncio import (  # ruff: ignore[typing-only-third-party-import]  # pytest-bdd evaluates step annotations.
    AsyncSession,
    async_sessionmaker,
)

from tests.steps.pricing_snapshots_support import PricingSnapshotContext
from tests.steps.vidaimock_harness import terminate_process_gracefully

if typ.TYPE_CHECKING:
    import collections.abc as cabc


@pytest.fixture
def pricing_context(
    tmp_path: pathlib.Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> cabc.Iterator[PricingSnapshotContext]:
    """Share state between steps and stop any Vidai Mock child."""
    context = PricingSnapshotContext(
        directory=tmp_path,
        session_factory=session_factory,
    )
    yield context
    if context.process is not None:
        terminate_process_gracefully(context.process, context.stderr_file)


@scenario(
    "../features/pricing_snapshots.feature",
    "A pinned run reprices identically after its rate card is revised",
)
def test_pinned_run_reprices_after_revision() -> None:
    """Run the pinned-run revision scenario."""


@scenario(
    "../features/pricing_snapshots.feature",
    "A pinned run keeps pricing after its rate card file is deleted",
)
def test_pinned_run_survives_card_deletion() -> None:
    """Run the pinned-run deletion scenario."""


@scenario(
    "../features/pricing_snapshots.feature",
    "A text-to-speech rate card prices characters and audio duration",
)
def test_tts_card_prices_characters_and_duration() -> None:
    """Run the TTS pricing scenario."""


@scenario(
    "../features/pricing_snapshots.feature",
    "A helper-service SLA4OAI plan document is preserved",
)
def test_helper_plan_document_is_preserved() -> None:
    """Run the SLA4OAI document-preservation scenario."""


@scenario(
    "../features/pricing_snapshots.feature",
    "A tampered pricing snapshot row is refused",
)
def test_tampered_snapshot_is_refused() -> None:
    """Run the tampered-row scenario."""


@scenario(
    "../features/pricing_snapshots.feature",
    "A Vidai Mock completion is priced from the persisted snapshot",
)
def test_vidaimock_completion_uses_persisted_snapshot() -> None:
    """Run the live-provider pricing scenario."""
