"""Behavioural tests for immutable, content-addressed pricing snapshots."""

from __future__ import annotations

import asyncio  # ruff: ignore[typing-only-standard-library-import]  # pytest-bdd evaluates step annotations.
import pathlib  # ruff: ignore[typing-only-standard-library-import]  # pytest-bdd evaluates step annotations.
import typing as typ

import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy.ext.asyncio import (  # ruff: ignore[typing-only-third-party-import]  # pytest-bdd evaluates step annotations.
    AsyncSession,
    async_sessionmaker,
)

from episodic.cost import PricingSnapshotIntegrityError
from episodic.cost.engine import PricingEngine, PricingRequest
from episodic.llm import LLMRequest
from episodic.llm.openai_api.adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from tests.fixtures.cost import v1_pricing_snapshot
from tests.steps.pricing_snapshots_support import (
    REVISED_RUN_ID,
    SLA4OAI_DOCUMENT,
    TTS_SUBJECT,
    TTS_USAGE,
    PricingSnapshotContext,
    build_catalogue,
    helper_plan_snapshot,
    persist_and_read,
    pin_llm_run,
    read_stored_snapshot,
    record_llm_call,
    reprice_from_stored_snapshot,
    tamper_stored_rates,
    write_llm_card,
    write_tts_card,
)
from tests.steps.pricing_snapshots_vidaimock import (
    write_pricing_provider_config,
    write_pricing_response_template,
)
from tests.steps.vidaimock_harness import (
    start_vidaimock_process,
    terminate_process_gracefully,
)

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


@given("a gpt-4o-mini rate card charging 8 minor units per million cached input tokens")
def llm_rate_card(pricing_context: PricingSnapshotContext) -> None:
    """Write the pre-correction gpt-4o-mini card."""
    write_llm_card(pricing_context.directory, cached_minor="8")


@given("a generation run pinned to that rate card")
def pinned_run(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Pin the run before its card is revised or deleted."""
    _function_scoped_runner.run(
        pin_llm_run(
            pricing_context.session_factory,
            pricing_context.directory,
            pricing_context.run_id,
        )
    )


@given("a TTS rate card charging 1500 minor units per 1000000 input characters")
def tts_character_card(pricing_context: PricingSnapshotContext) -> None:
    """Write the TTS card without its audio-duration rate yet."""
    write_tts_card(pricing_context.directory, include_audio=False)


@given("the TTS rate card charges 5 minor units per 60000 output audio milliseconds")
def tts_audio_card(pricing_context: PricingSnapshotContext) -> None:
    """Complete the TTS card with its audio-duration rate."""
    write_tts_card(pricing_context.directory)


@given('an SLA4OAI plans document for the helper service "pedante"')
def helper_plan(pricing_context: PricingSnapshotContext) -> None:
    """Prepare the helper-service snapshot carrying the plan document."""
    pricing_context.snapshot = helper_plan_snapshot(SLA4OAI_DOCUMENT)


@given("a persisted gpt-4o-mini pricing snapshot")
def persisted_snapshot(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Persist the fixture snapshot so it can be tampered with."""
    (
        pricing_context.stored_snapshot_id,
        pricing_context.stored,
    ) = _function_scoped_runner.run(
        persist_and_read(pricing_context.session_factory, v1_pricing_snapshot())
    )


@given(
    "a Vidai Mock server reporting 2000000 prompt tokens of which 1000000 are "
    "cached and 500000 completion tokens"
)
def vidaimock_server(pricing_context: PricingSnapshotContext) -> None:
    """Start a Vidai Mock server reporting a cached-token split."""
    provider_dir = pricing_context.directory / "providers"
    template_dir = pricing_context.directory / "templates" / "pricing"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    write_pricing_provider_config(provider_dir)
    write_pricing_response_template(template_dir)
    start_vidaimock_process(
        pricing_context,
        pricing_context.directory,
        label="the pricing behavioural test",
    )


@given(
    "a generation run pinned to a gpt-4o-mini rate card charging 8 minor units "
    "per million cached input tokens"
)
def pinned_llm_card(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Write the pre-correction card and pin the run to it."""
    write_llm_card(pricing_context.directory, cached_minor="8")
    _function_scoped_runner.run(
        pin_llm_run(
            pricing_context.session_factory,
            pricing_context.directory,
            pricing_context.run_id,
        )
    )


@when(
    "the run records a call with 1000000 input tokens and 1000000 cached input tokens"
)
def record_pinned_call(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Record one call priced by the pinned snapshot."""
    usage = {"input_tokens": 1_000_000, "cached_input_tokens": 1_000_000}
    pricing_context.usage = usage
    pricing_context.recorded = _function_scoped_runner.run(
        record_llm_call(
            pricing_context.session_factory,
            pricing_context.directory,
            pricing_context.run_id,
            usage,
            call_label="first",
        )
    )


@when(
    "the rate card file is revised to charge 7.5 minor units per million "
    "cached input tokens"
)
def revise_card(pricing_context: PricingSnapshotContext) -> None:
    """Rewrite the card in place with the corrected cached-input rate."""
    write_llm_card(pricing_context.directory, cached_minor="7.5")


@when("the rate card file is deleted")
def delete_card(pricing_context: PricingSnapshotContext) -> None:
    """Remove the card after the run is pinned."""
    (pricing_context.directory / "openai-2026-05.yaml").unlink()


@when("the rate card is persisted and read back")
def persist_tts_card(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Persist the TTS snapshot and read it back."""
    snapshot = _function_scoped_runner.run(
        build_catalogue(pricing_context.directory).resolve(TTS_SUBJECT)
    )
    pricing_context.snapshot = snapshot
    (
        pricing_context.stored_snapshot_id,
        pricing_context.stored,
    ) = _function_scoped_runner.run(
        persist_and_read(pricing_context.session_factory, snapshot)
    )


@when("the helper pricing snapshot is persisted and read back")
def persist_helper_snapshot(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Persist the helper snapshot and read it back."""
    assert pricing_context.snapshot is not None, (
        "the SLA4OAI document must be prepared before persisting"
    )
    (
        pricing_context.stored_snapshot_id,
        pricing_context.stored,
    ) = _function_scoped_runner.run(
        persist_and_read(pricing_context.session_factory, pricing_context.snapshot)
    )


@when("its rates are altered directly in the database")
def tamper_rates(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Alter the stored rates without updating the content hash."""
    assert pricing_context.stored_snapshot_id is not None, (
        "the snapshot must be persisted before it can be tampered with"
    )
    _function_scoped_runner.run(
        tamper_stored_rates(
            pricing_context.session_factory,
            pricing_context.stored_snapshot_id,
        )
    )


@when(
    "the run completes a chat completion through the OpenAI-compatible "
    "adapter and records its cost"
)
def complete_and_record(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Call Vidai Mock through the adapter and record the reported usage."""

    async def _call() -> None:
        """Run one chat completion and record its provider-reported cost."""
        config = OpenAICompatibleLLMConfig(
            base_url=pricing_context.base_url,
            api_key="test-key",
        )
        async with OpenAICompatibleLLMAdapter(config=config) as adapter:
            response = await adapter.generate(
                LLMRequest(model="gpt-4o-mini", prompt="price this call")
            )
        usage = response.provider_call_usage
        assert usage is not None, "the provider must report usage for pricing"
        pricing_context.usage = dict(usage.usage_metrics)
        pricing_context.recorded = await record_llm_call(
            pricing_context.session_factory,
            pricing_context.directory,
            pricing_context.run_id,
            pricing_context.usage,
            call_label="vidaimock",
            model=response.model,
            usage_source=usage.usage_source,
        )

    _function_scoped_runner.run(_call())


@then(parsers.parse("the run's ledger entry costs {expected:d} minor units"))
def ledger_entry_costs(
    pricing_context: PricingSnapshotContext,
    expected: int,
) -> None:
    """Assert the recorded call costs the rate the run was pinned to."""
    assert pricing_context.recorded is not None, "the run must have recorded a call"
    assert pricing_context.recorded.cost_minor == expected, (
        f"expected {expected} minor units, got {pricing_context.recorded.cost_minor}"
    )


@then(
    parsers.parse(
        "repricing the ledger entry from its persisted snapshot costs "
        "{expected:d} minor units"
    )
)
def reprice_from_snapshot(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
    expected: int,
) -> None:
    """Assert the stored snapshot keeps pricing the original usage unchanged."""
    assert pricing_context.recorded is not None, "the run must have recorded a call"
    cost = _function_scoped_runner.run(
        reprice_from_stored_snapshot(
            pricing_context.session_factory,
            pricing_context.recorded.pricing_snapshot_id,
            pricing_context.usage,
            "chat_completions",
        )
    )
    assert cost == expected, (
        f"expected {expected} minor units from the stored snapshot, got {cost}"
    )


@then(
    parsers.parse(
        "a new run pinned after the revision prices the same usage at "
        "{expected:d} minor units"
    )
)
def revised_run_cost(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
    expected: int,
) -> None:
    """Assert a run pinned after the revision prices the same usage at the new rate."""
    _assert_revised_run_cost(pricing_context, _function_scoped_runner, expected)


@then("the stored snapshot equals the rate card")
def stored_equals_card(pricing_context: PricingSnapshotContext) -> None:
    """Assert the persisted snapshot round-trips every field unchanged."""
    assert pricing_context.stored is not None, "the snapshot must have been read back"
    assert pricing_context.snapshot is not None, "the rate card must have been loaded"
    assert pricing_context.stored == pricing_context.snapshot, (
        "the stored snapshot must equal the loaded rate card"
    )


@then(
    "usage of 2000000 input characters and 120000 output audio milliseconds "
    "costs 3010 minor units"
)
def tts_cost(pricing_context: PricingSnapshotContext) -> None:
    """Characters and audio duration price at their own rates."""
    assert pricing_context.stored is not None, "the snapshot must have been read back"
    cost = PricingEngine.price(
        pricing_context.stored,
        PricingRequest(usage=TTS_USAGE, operation="tts"),
    ).computed_cost_minor
    assert cost == 3010, f"expected 3010 minor units for the TTS usage, got {cost}"


@then("the stored source document text is identical to the original")
def document_preserved(pricing_context: PricingSnapshotContext) -> None:
    """Assert the verbatim source document survives persistence."""
    assert pricing_context.stored is not None, "the snapshot must have been read back"
    document = pricing_context.stored.source_document
    assert document is not None, "the stored helper snapshot must carry its document"
    assert document.content == SLA4OAI_DOCUMENT, (
        "the stored source document must be byte-identical to the original"
    )


@then("changing one character of the document produces a different content hash")
def hash_tracks_document(pricing_context: PricingSnapshotContext) -> None:
    """Assert a single-character edit changes the content address."""
    assert pricing_context.stored is not None, "the snapshot must have been read back"
    # One character differs: the capital P in the plan's display name.
    altered = helper_plan_snapshot(SLA4OAI_DOCUMENT.replace("Pedante", "pedante"))
    assert altered.content_hash != pricing_context.stored.content_hash, (
        "a changed source document must produce a different content hash"
    )


@then("reading the snapshot fails with a pricing snapshot integrity error")
def tampered_read_fails(
    pricing_context: PricingSnapshotContext,
    _function_scoped_runner: asyncio.Runner,
) -> None:
    """Assert the tampered row is refused rather than priced."""
    assert pricing_context.stored_snapshot_id is not None, (
        "the snapshot must be persisted before reading it"
    )
    with pytest.raises(PricingSnapshotIntegrityError):
        _function_scoped_runner.run(
            read_stored_snapshot(
                pricing_context.session_factory,
                pricing_context.stored_snapshot_id,
            )
        )


def _assert_revised_run_cost(
    pricing_context: PricingSnapshotContext,
    runner: asyncio.Runner,
    expected: int,
) -> None:
    """Pin and record a fresh run, then assert its revised-card cost."""
    runner.run(
        pin_llm_run(
            pricing_context.session_factory,
            pricing_context.directory,
            REVISED_RUN_ID,
        )
    )
    recorded = runner.run(
        record_llm_call(
            pricing_context.session_factory,
            pricing_context.directory,
            REVISED_RUN_ID,
            pricing_context.usage,
            call_label="first",
        )
    )
    assert recorded.cost_minor == expected, (
        f"expected {expected} minor units after the revision, got {recorded.cost_minor}"
    )
