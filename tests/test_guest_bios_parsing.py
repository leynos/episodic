"""Guest biography response parsing tests."""

import pytest

from episodic.generation.guest_bios import (
    GuestBiosGenerator,
    GuestBiosResponseFormatError,
)
from tests._guest_bios_helpers import _response


@pytest.mark.parametrize(
    ("revision_id_in_response", "expected_revision_ids", "error_match"),
    [
        pytest.param(
            "rev-unknown",
            ("rev-ada",),
            "unknown revision",
            id="unknown",
        ),
        pytest.param(
            "rev-ada",
            ("rev-ada", "rev-grace"),
            "missing revision",
            id="missing",
        ),
    ],
)
def test_result_from_response_rejects_invalid_revision_identifier(
    revision_id_in_response: str,
    expected_revision_ids: tuple[str, ...],
    error_match: str,
) -> None:
    """Reject LLM output with an invalid source revision identifier."""
    response = _response({
        "guests": [
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace writes about analytical engines.",
                "reference_document_revision_id": revision_id_in_response,
            }
        ]
    })

    with pytest.raises(GuestBiosResponseFormatError, match=error_match):
        GuestBiosGenerator.result_from_response(
            response,
            expected_revision_ids=expected_revision_ids,
        )


def test_result_from_response_rejects_duplicate_revision_identifier() -> None:
    """Reject LLM output that emits two biographies for one source revision."""
    response = _response({
        "guests": [
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace writes about analytical engines.",
                "reference_document_revision_id": "rev-ada",
            },
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace studies computing history.",
                "reference_document_revision_id": "rev-ada",
            },
        ]
    })

    with pytest.raises(GuestBiosResponseFormatError, match="duplicate revision"):
        GuestBiosGenerator.result_from_response(
            response,
            expected_revision_ids=("rev-ada",),
        )
