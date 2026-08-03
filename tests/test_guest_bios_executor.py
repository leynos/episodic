"""Tests for GuestBiosToolExecutor."""

import asyncio
import json
import typing as typ
from uuid import UUID, uuid4

import pytest

from episodic.canonical.reference_documents.resolution import ResolvedBinding
from episodic.generation import GuestBiosGeneratorConfig
from episodic.orchestration import (
    ActionKind,
    GenerationOrchestrationRequest,
    GuestBiosToolExecutor,
)
from tests._guest_bios_executor_helpers import (
    SCRIPT_TEI,
    _guest_bios_action,
    _reference_binding,
    _reference_document,
    _reference_revision,
    _resolved_guest_binding,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _response,
    _usage,
)
from tests.snapshot_redaction import redact_snapshot_uuids

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_resolves_bindings_and_returns_result(
    snapshot: SnapshotAssertion,
) -> None:
    """Guest-bios execution should resolve profile bindings and enrich TEI."""
    ids = {
        "document": UUID("018fdcf0-0000-7000-8000-000000000001"),
        "revision": UUID("018fdcf0-0000-7000-8000-000000000002"),
        "series_profile": UUID("018fdcf0-0000-7000-8000-000000000003"),
        "episode": UUID("018fdcf0-0000-7000-8000-000000000004"),
        "template": UUID("018fdcf0-0000-7000-8000-000000000005"),
    }
    calls: list[dict[str, object]] = []

    async def binding_resolver(
        uow: object,
        **kwargs: object,
    ) -> list[ResolvedBinding]:
        await asyncio.sleep(0)
        calls.append({"uow": uow, **kwargs})
        return [
            ResolvedBinding(
                binding=_reference_binding(ids["revision"]),
                document=_reference_document(ids["document"]),
                revision=_reference_revision(
                    document_id=ids["document"],
                    revision_id=ids["revision"],
                ),
            )
        ]

    llm = _FakeLLMPort([
        _response(
            json.dumps({
                "guests": [
                    {
                        "display_name": "Ada Lovelace",
                        "bio": "Ada Lovelace wrote about analytical engines.",
                        "reference_document_revision_id": str(ids["revision"]),
                    }
                ]
            }),
            model="gpt-4o-mini",
            usage=_usage(input_tokens=30, output_tokens=12),
        )
    ])
    uow = object()
    executor = GuestBiosToolExecutor(
        llm=llm,
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", uow),
        binding_resolver=binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        template_structure={"sections": ["intro"]},
        series_profile_id=ids["series_profile"],
        episode_id=ids["episode"],
        template_id=ids["template"],
    )

    result = await executor.execute(_guest_bios_action(), request)

    stable_calls = redact_snapshot_uuids([
        {key: value for key, value in call.items() if key != "uow"} for call in calls
    ])
    assert stable_calls == snapshot, "actual output must match snapshot"
    assert all(call["uow"] is uow for call in calls), (
        "binding resolver calls must receive the executor's unit of work"
    )
    assert result.action_kind is ActionKind.GENERATE_GUEST_BIOS, (
        "Expected values to match"
    )
    assert result.usage == _usage(input_tokens=30, output_tokens=12), (
        "Expected values to match"
    )
    assert result.guest_bios_result is not None, "Expected value to be present"
    assert result.guest_bios_result.sources[0].reference_document_revision_id == str(
        ids["revision"]
    ), "Expected values to match"
    assert 'type="guest-bios"' in result.guest_bios_result.tei_xml, (
        "Expected collection to contain the value"
    )


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_uses_guest_bios_prompt_by_default() -> None:
    """Default guest-bios execution should not reuse the show-notes prompt."""
    revision_id = uuid4()

    async def binding_resolver(
        uow: object,
        **kwargs: object,
    ) -> list[ResolvedBinding]:
        del uow, kwargs
        await asyncio.sleep(0)
        return [
            _resolved_guest_binding(
                document_id=uuid4(),
                revision_id=revision_id,
            )
        ]

    llm = _FakeLLMPort([
        _response(
            json.dumps({
                "guests": [
                    {
                        "display_name": "Ada Lovelace",
                        "bio": "Ada Lovelace wrote about analytical engines.",
                        "reference_document_revision_id": str(revision_id),
                    }
                ]
            }),
            model="gpt-4o-mini",
            usage=_usage(input_tokens=30, output_tokens=12),
        )
    ])
    executor = GuestBiosToolExecutor(
        llm=llm,
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        binding_resolver=binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    await executor.execute(_guest_bios_action(), request)

    outbound_request = llm.requests[0]
    assert (
        outbound_request.system_prompt
        == GuestBiosGeneratorConfig(model="gpt-4o-mini").system_prompt
    ), "Expected values to match"
    assert outbound_request.system_prompt != _config().execution_system_prompt, (
        "Expected values to differ"
    )


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_allows_no_sources_no_op() -> None:
    """Guest-bios plans with no bound guest profiles should complete as no-ops."""

    async def binding_resolver(
        uow: object,
        **kwargs: object,
    ) -> list[ResolvedBinding]:
        del uow, kwargs
        await asyncio.sleep(0)
        return []

    llm = _FakeLLMPort([])
    executor = GuestBiosToolExecutor(
        llm=llm,
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        binding_resolver=binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    result = await executor.execute(_guest_bios_action(), request)

    assert result.model == _config().execution_model, "Expected values to match"
    assert result.summary == "Generated 0 guest biographies.", (
        "Expected values to match"
    )
    assert result.usage == _usage(input_tokens=0, output_tokens=0), (
        "Expected values to match"
    )
    assert result.guest_bios_result is not None, "Expected value to be present"
    assert not result.guest_bios_result.generation_result.model, (
        "Expected condition to be false"
    )
    assert result.guest_bios_result.sources == (), "Expected values to match"
    assert result.guest_bios_result.tei_xml == request.script_tei_xml, (
        "Expected values to match"
    )
    assert not llm.requests, "Expected condition to be false"
