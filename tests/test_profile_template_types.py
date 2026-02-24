"""Unit tests for profile/template exception metadata types."""

from __future__ import annotations

import typing as typ

import pytest

from episodic.canonical.profile_templates.types import (
    EntityNotFoundError,
    ProfileTemplateError,
    RevisionConflictError,
)


@pytest.mark.parametrize(
    (
        "error_cls",
        "kwargs",
        "expected_message",
        "expected_code",
        "expected_entity_id",
        "expected_retryable",
    ),
    [
        pytest.param(
            ProfileTemplateError,
            {"message": "base failure"},
            "base failure",
            "profile_template_error",
            None,
            False,
            id="profile-template-error-defaults",
        ),
        pytest.param(
            EntityNotFoundError,
            {"message": "profile missing", "entity_id": "p-123"},
            "profile missing",
            "entity_not_found",
            "p-123",
            False,
            id="entity-not-found-defaults",
        ),
        pytest.param(
            RevisionConflictError,
            {"message": "revision conflict", "entity_id": "t-123"},
            "revision conflict",
            "revision_conflict",
            "t-123",
            True,
            id="revision-conflict-defaults",
        ),
    ],
)
def test_error_class_defaults(
    error_cls: type[ProfileTemplateError],
    kwargs: dict[str, typ.Any],
    expected_message: str,
    expected_code: str,
    expected_entity_id: str | None,
    expected_retryable: object,
) -> None:
    """Errors should expose class-level defaults when values are omitted."""
    error = error_cls(**kwargs)

    assert str(error) == expected_message, "Expected message to be preserved."
    assert error.code == expected_code, "Expected default error code."
    assert error.entity_id == expected_entity_id, (
        "Expected default or provided entity identifier."
    )
    assert error.retryable is expected_retryable, (
        "Expected default or provided retryability."
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
