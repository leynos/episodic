"""JSON parsing tests for Pedante evaluator responses."""

import json

import pytest

import tests.test_pedante_support as pedante_support
from episodic.llm import LLMUsage
from episodic.qa.pedante import PedanteEvaluationResult, PedanteResponseFormatError


def test_pedante_parse_result_rejects_invalid_json() -> None:
    """Reject malformed structured output deterministically."""
    with pytest.raises(PedanteResponseFormatError, match="valid JSON object"):
        PedanteEvaluationResult.from_json("not json", usage=LLMUsage(1, 2, 3))


@pytest.mark.parametrize("payload", ["[]", "42", '"string"', "null", "true"])
def test_pedante_parse_result_rejects_non_object_json(payload: str) -> None:
    """Reject syntactically valid JSON that is not a JSON object."""
    with pytest.raises(PedanteResponseFormatError, match="valid JSON object"):
        PedanteEvaluationResult.from_json(payload, usage=LLMUsage(1, 2, 3))


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"findings": [pedante_support.valid_finding_payload()]}, "summary"),
        (
            {
                "summary": "   ",
                "findings": [pedante_support.valid_finding_payload()],
            },
            "summary",
        ),
        ({"summary": "Summary."}, "findings"),
    ],
    ids=["missing_summary", "blank_summary", "missing_findings"],
)
def test_pedante_parse_result_rejects_invalid_top_level_fields(
    payload: dict[str, object],
    match: str,
) -> None:
    """Reject payloads with missing or blank top-level fields."""
    with pytest.raises(PedanteResponseFormatError, match=match):
        PedanteEvaluationResult.from_json(json.dumps(payload), usage=LLMUsage(1, 2, 3))


def _assert_parse_rejects(payload: object, match: str) -> None:
    """Assert that ``from_json`` raises ``PedanteResponseFormatError`` for *payload*."""
    with pytest.raises(PedanteResponseFormatError, match=match):
        PedanteEvaluationResult.from_json(
            json.dumps(payload),
            usage=LLMUsage(1, 2, 3),
        )


@pytest.mark.parametrize(
    "findings_value",
    ["not-a-list", 42, {"not": "a-list"}],
    ids=["string", "integer", "object"],
)
def test_pedante_parse_result_rejects_non_list_findings(
    findings_value: object,
) -> None:
    """Reject findings that are not a list."""
    _assert_parse_rejects(
        {"summary": "Summary.", "findings": findings_value},
        "findings",
    )


@pytest.mark.parametrize(
    "item",
    [1, "not-an-object", None, True],
    ids=["integer", "string", "null", "boolean"],
)
def test_pedante_parse_result_rejects_non_object_finding_items(
    item: object,
) -> None:
    """Reject findings list items that are not JSON objects."""
    _assert_parse_rejects(
        {"summary": "Summary.", "findings": [item]},
        "finding must be a JSON",
    )


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("support_level", "mystery_value"),
        ("claim_kind", "not-a-valid-kind"),
        ("severity", "not-a-valid-severity"),
    ],
)
def test_pedante_parse_result_rejects_invalid_enum_values(
    field_name: str,
    bad_value: str,
) -> None:
    """Reject findings with invalid claim_kind, support_level, or severity values."""
    _assert_parse_rejects(
        pedante_support.valid_result_payload(
            findings=[pedante_support.valid_finding_payload(**{field_name: bad_value})]
        ),
        field_name,
    )


@pytest.mark.parametrize(
    "bad_ids",
    [
        "not-a-list",
        42,
        [1, 2],
        ["", "src-2"],
        ["   "],
    ],
    ids=[
        "string",
        "integer",
        "non-string-items",
        "empty-string-item",
        "blank-string-item",
    ],
)
def test_pedante_parse_result_rejects_invalid_cited_source_ids(
    bad_ids: object,
) -> None:
    """Reject findings with invalid cited_source_ids field."""
    _assert_parse_rejects(
        pedante_support.valid_result_payload(
            findings=[pedante_support.valid_finding_payload(cited_source_ids=bad_ids)]
        ),
        "cited_source_ids",
    )
