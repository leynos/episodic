"""Tests for GuestBiosToolExecutor."""

# pylint: disable=too-many-lines

import asyncio
import datetime as dt
import json
import typing as typ
from uuid import UUID, uuid4

import pytest

import episodic.orchestration._guest_bios_executor as guest_bios_executor_module
from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.reference_documents.resolution import ResolvedBinding
from episodic.generation import (
    GuestBiosGeneratorConfig,
    GuestBioSource,
    GuestBiosResponseFormatError,
    GuestBiosResult,
)
from episodic.llm import (
    LLMError,
    LLMProviderResponseError,
    LLMTransientProviderError,
)
from episodic.orchestration import (
    ActionKind,
    GenerationOrchestrationRequest,
    GuestBiosFormatError,
    GuestBiosToolExecutor,
    ModelTier,
    PlannedAction,
    ToolExecutionError,
    UnsupportedActionError,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _response,
    _usage,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork
    from episodic.generation import GuestBiosGenerator
    from episodic.llm import LLMPort


SCRIPT_TEI = """\
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <title>Guest Bio Executor Fixture</title>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <p>Welcome to the episode.</p>
    </body>
  </text>
</TEI>
"""


def _reference_document(document_id: UUID) -> ReferenceDocument:
    return ReferenceDocument(
        id=document_id,
        owner_series_profile_id=uuid4(),
        kind=ReferenceDocumentKind.GUEST_PROFILE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={},
        created_at=dt.datetime.now(dt.UTC),
        updated_at=dt.datetime.now(dt.UTC),
    )


def _reference_revision(
    *,
    document_id: UUID,
    revision_id: UUID,
) -> ReferenceDocumentRevision:
    return ReferenceDocumentRevision(
        id=revision_id,
        reference_document_id=document_id,
        content={
            "display_name": "Ada Lovelace",
            "profile": "Ada wrote notes on the Analytical Engine.",
        },
        content_hash="hash",
        author=None,
        change_note=None,
        created_at=dt.datetime.now(dt.UTC),
    )


def _reference_binding(revision_id: UUID) -> ReferenceBinding:
    return ReferenceBinding(
        id=uuid4(),
        reference_document_revision_id=revision_id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=uuid4(),
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=dt.datetime.now(dt.UTC),
    )


def _guest_bios_action() -> PlannedAction:
    return PlannedAction(
        action_id="guest-bios-1",
        action_kind=ActionKind.GENERATE_GUEST_BIOS,
        rationale="Guest profiles are bound to this episode.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml", "series_profile_id"),
    )


def _resolved_guest_binding(
    *,
    document_id: UUID,
    revision_id: UUID,
) -> ResolvedBinding:
    """Build one resolved guest-profile binding for executor tests."""
    return ResolvedBinding(
        binding=_reference_binding(revision_id),
        document=_reference_document(document_id),
        revision=_reference_revision(
            document_id=document_id,
            revision_id=revision_id,
        ),
    )


async def _single_guest_binding_resolver(
    uow: object,
    **kwargs: object,
) -> list[ResolvedBinding]:
    """Return one guest-profile binding after one async scheduling point."""
    del uow, kwargs
    await asyncio.sleep(0)
    return [
        _resolved_guest_binding(
            document_id=uuid4(),
            revision_id=uuid4(),
        )
    ]


class _RaisingGuestBiosGenerator:
    """Raise a configured exception from the guest-bios generator boundary."""

    def __init__(
        self,
        error: BaseException,
        *,
        expected_template_structure: dict[str, object] | None = None,
    ) -> None:
        self._error = error
        self._expected_template_structure = expected_template_structure

    async def generate(
        self,
        script_tei_xml: str,
        sources: tuple[GuestBioSource, ...],
        *,
        template_structure: dict[str, object] | None = None,
    ) -> GuestBiosResult:
        """Raise the configured error after validating call context."""
        assert script_tei_xml == SCRIPT_TEI.strip()
        assert sources
        assert template_structure == self._expected_template_structure
        raise self._error


class _CustomLLMError(LLMError):
    """LLM error subclass without a dedicated log event mapping."""


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_resolves_bindings_and_returns_result() -> None:
    """Guest-bios execution should resolve profile bindings and enrich TEI."""
    ids = {
        "document": uuid4(),
        "revision": uuid4(),
        "series_profile": uuid4(),
        "episode": uuid4(),
        "template": uuid4(),
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

    assert calls == [
        {
            "uow": uow,
            "series_profile_id": ids["series_profile"],
            "episode_id": ids["episode"],
            "template_id": ids["template"],
        }
    ]
    assert result.action_kind is ActionKind.GENERATE_GUEST_BIOS
    assert result.usage == _usage(input_tokens=30, output_tokens=12)
    assert result.guest_bios_result is not None
    assert result.guest_bios_result.sources[0].reference_document_revision_id == str(
        ids["revision"]
    )
    assert 'type="guest-bios"' in result.guest_bios_result.tei_xml


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
    )
    assert outbound_request.system_prompt != _config().execution_system_prompt


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_requires_series_profile_id() -> None:
    """Binding-backed guest-bios execution needs a series profile context."""
    executor = GuestBiosToolExecutor(
        llm=_FakeLLMPort([]),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
    )

    with pytest.raises(ToolExecutionError, match="series_profile_id"):
        await executor.execute(_guest_bios_action(), request)


@pytest.mark.asyncio
async def test_guest_bios_executor_wraps_format_error_distinctly() -> None:
    """Structured guest-bios validation errors should keep a distinct wrapper."""
    generator_error = GuestBiosResponseFormatError("guests must be a list.")
    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast(
            "GuestBiosGenerator", _RaisingGuestBiosGenerator(generator_error)
        ),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    with pytest.raises(
        GuestBiosFormatError,
        match="malformed structured JSON",
    ) as exc_info:
        await executor.execute(_guest_bios_action(), request)

    assert exc_info.value.__cause__ is generator_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            LLMTransientProviderError("provider transiently failed"),
            id="transient_provider_error",
        ),
        pytest.param(
            LLMProviderResponseError("provider rejected the response"),
            id="provider_response_error",
        ),
    ],
)
async def test_guest_bios_executor_propagates_llm_provider_errors(
    error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider errors should surface unchanged and emit provider log context."""
    events: list[tuple[str, str, dict[str, object]]] = []

    def capture_log_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(
        guest_bios_executor_module,
        "_log_event",
        capture_log_event,
    )
    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast("GuestBiosGenerator", _RaisingGuestBiosGenerator(error)),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    with pytest.raises(type(error)) as exc_info:
        await executor.execute(_guest_bios_action(), request)

    assert exc_info.value is error
    assert any(
        message.startswith("guest_bios_tool_executor.execute")
        and fields.get("error_type") == type(error).__name__
        for _, message, fields in events
    )


@pytest.mark.asyncio
async def test_guest_bios_executor_wraps_unexpected_generator_error() -> None:
    """Unexpected generator failures should become ToolExecutionError."""
    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast(
            "GuestBiosGenerator",
            _RaisingGuestBiosGenerator(RuntimeError("boom")),
        ),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    with pytest.raises(ToolExecutionError, match="guest-bios tool execution failed"):
        await executor.execute(_guest_bios_action(), request)


@pytest.mark.asyncio
async def test_guest_bios_executor_logs_unknown_llm_subclass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmapped LLM errors should use the generic provider log event."""
    error = _CustomLLMError("custom provider failure")
    events: list[tuple[str, str, dict[str, object]]] = []

    def capture_log_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast("GuestBiosGenerator", _RaisingGuestBiosGenerator(error)),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    monkeypatch.setattr(
        guest_bios_executor_module,
        "_log_event",
        capture_log_event,
    )

    with pytest.raises(_CustomLLMError):
        await executor.execute(_guest_bios_action(), request)

    assert any(
        message == "guest_bios_tool_executor.execute.llm_error"
        and fields.get("error_type") == "_CustomLLMError"
        for _, message, fields in events
    )


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_rejects_show_notes_action() -> None:
    """The guest-bios executor should not accept another action kind."""
    executor = GuestBiosToolExecutor(
        llm=_FakeLLMPort([]),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
    )
    action = PlannedAction(
        action_id="show-notes-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Wrong executor.",
        model_tier=ModelTier.EXECUTION,
    )

    with pytest.raises(UnsupportedActionError, match="guest-bios tool"):
        await executor.execute(
            action,
            GenerationOrchestrationRequest(
                correlation_id="corr",
                script_tei_xml=SCRIPT_TEI,
                series_profile_id=uuid4(),
            ),
        )
