"""Unit tests for profile/template exception metadata types."""

from __future__ import annotations

from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    RevisionConflictError,
)
from episodic.canonical.profile_templates.types import ProfileTemplateError


def test_profile_template_error_uses_class_defaults() -> None:
    """Base errors should use default class metadata when unset."""
    error = ProfileTemplateError("base failure")

    assert str(error) == "base failure", "Expected message to be preserved."
    assert error.code == "profile_template_error", "Expected base default code."
    assert error.entity_id is None, "Expected empty entity identifier by default."
    assert error.retryable is False, "Expected non-retryable base default."


def test_entity_not_found_error_defaults() -> None:
    """Entity-not-found errors should expose canonical defaults."""
    error = EntityNotFoundError("profile missing", entity_id="p-123")

    assert str(error) == "profile missing", "Expected message to be preserved."
    assert error.code == "entity_not_found", "Expected entity-not-found code."
    assert error.entity_id == "p-123", "Expected provided entity identifier."
    assert error.retryable is False, "Expected entity-not-found to be non-retryable."


def test_revision_conflict_error_defaults() -> None:
    """Revision-conflict errors should keep the existing retryable default."""
    error = RevisionConflictError("revision conflict", entity_id="t-123")

    assert str(error) == "revision conflict", "Expected message to be preserved."
    assert error.code == "revision_conflict", "Expected revision-conflict code."
    assert error.entity_id == "t-123", "Expected provided entity identifier."
    assert error.retryable is True, "Expected revision conflict to default retryable."


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
        error_code = "custom_profile_template_error"
        default_retryable = True

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
