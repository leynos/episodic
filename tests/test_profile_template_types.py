"""Unit tests for profile/template exception metadata types."""

from __future__ import annotations

import dataclasses as dc
from typing import TYPE_CHECKING  # noqa: ICN003 - used for type-only imports; see TYP-KWARGS-001

import pytest

from episodic.canonical.profile_templates.types import (
    EntityNotFoundError,
    ProfileTemplateError,
    RevisionConflictError,
)

if TYPE_CHECKING:
    import typing as typ


@dc.dataclass(slots=True, frozen=True)
class _ExpectedError:
    """Expected error payload for parametrized exception tests."""

    message: str
    code: str
    entity_id: str | None
    retryable: bool


@pytest.mark.parametrize(
    (
        "error_cls",
        "kwargs",
        "expected",
    ),
    [
        pytest.param(
            ProfileTemplateError,
            {"message": "base failure"},
            _ExpectedError(
                message="base failure",
                code="profile_template_error",
                entity_id=None,
                retryable=False,
            ),
            id="profile-template-error-defaults",
        ),
        pytest.param(
            EntityNotFoundError,
            {"message": "profile missing", "entity_id": "p-123"},
            _ExpectedError(
                message="profile missing",
                code="entity_not_found",
                entity_id="p-123",
                retryable=False,
            ),
            id="entity-not-found-defaults",
        ),
        pytest.param(
            RevisionConflictError,
            {"message": "revision conflict", "entity_id": "t-123"},
            _ExpectedError(
                message="revision conflict",
                code="revision_conflict",
                entity_id="t-123",
                retryable=True,
            ),
            id="revision-conflict-defaults",
        ),
        pytest.param(
            RevisionConflictError,
            {"message": "revision conflict", "retryable": False},
            _ExpectedError(
                message="revision conflict",
                code="revision_conflict",
                entity_id=None,
                retryable=False,
            ),
            id="revision-conflict-retryable-override",
        ),
    ],
)
def test_error_class_defaults(
    *,
    error_cls: type[ProfileTemplateError],
    kwargs: dict[str, str | bool | None],
    expected: _ExpectedError,
) -> None:
    """Errors should expose class-level defaults when values are omitted."""
    error = error_cls(**kwargs)  # pyright: ignore[reportUnknownArgumentType]  # ty: ignore[invalid-argument-type]  # https://github.com/leynos/episodic/issues/27

    assert str(error) == expected.message, (
        f"expected message {expected.message!r} but got {str(error)!r}"
    )
    assert error.code == expected.code, (
        f"expected error.code {expected.code!r} but got {error.code!r}"
    )
    assert error.entity_id == expected.entity_id, (
        "expected error.entity_id "
        f"{expected.entity_id!r} but got {error.entity_id!r}"
    )
    assert error.retryable is expected.retryable, (
        "expected error.retryable "
        f"{expected.retryable!r} but got {error.retryable!r}"
    )


def test_subclass_constructor_allows_code_override() -> None:
    """Subclass constructors should accept optional explicit error-code overrides."""
    error = EntityNotFoundError(
        "entity missing",
        code="custom_not_found",
        entity_id="p-999",
        retryable=True,
    )

    assert error.code == "custom_not_found", "Expected explicit code override."
    assert error.entity_id == "p-999", "Expected provided entity identifier."
    assert error.retryable is True, "Expected explicit retryable override."


def test_custom_subclass_uses_class_level_defaults() -> None:
    """Custom subclasses should inherit default metadata behavior."""

    class CustomProfileTemplateError(ProfileTemplateError):
        error_code: typ.ClassVar[str] = "custom_profile_template_error"
        default_retryable: typ.ClassVar[bool] = True

    error = CustomProfileTemplateError("custom failure", entity_id="custom-123")

    assert str(error) == "custom failure", "Expected message to be preserved."
    assert error.code == "custom_profile_template_error", (
        "Expected subclass-level error code to be used."
    )
    assert error.entity_id == "custom-123", "Expected provided entity identifier."
    assert error.retryable is True, "Expected subclass-level retryable default."


def test_subclass_constructor_uses_default_when_code_is_none() -> None:
    """Passing code=None should still use subclass default error metadata."""
    error = EntityNotFoundError(
        "entity missing",
        code=None,
        entity_id="p-321",
    )

    assert error.code == "entity_not_found", (
        "Expected subclass default code when code is None."
    )
    assert error.entity_id == "p-321", "Expected provided entity identifier."
    assert error.retryable is False, "Expected subclass retryable default to apply."
