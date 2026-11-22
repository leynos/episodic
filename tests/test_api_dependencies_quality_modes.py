"""ApiDependencies contract for the accepted quality-mode capability set."""

import dataclasses as dc
import typing as typ

import pytest

from episodic.api import ApiDependencies
from episodic.canonical.generation_quality import QualityMode


def _dependencies(**overrides: object) -> ApiDependencies:
    """Build minimal dependencies with the supplied overrides."""
    base: dict[str, object] = {
        "uow_factory": lambda: None,
        "accepted_quality_modes": frozenset({QualityMode.DRAFT_WITHOUT_QA}),
    }
    base.update(overrides)
    return ApiDependencies(**typ.cast("dict[str, typ.Any]", base))


def test_accepted_modes_must_include_no_qa() -> None:
    """A deployment that cannot run draft_without_qa is rejected."""
    with pytest.raises(ValueError, match="must include draft_without_qa"):
        _dependencies(accepted_quality_modes=frozenset({QualityMode.QA_GATED}))


def test_accepted_modes_are_frozen() -> None:
    """A mutable supplied set is stored as an immutable frozenset."""
    supplied = {QualityMode.DRAFT_WITHOUT_QA}
    dependencies = _dependencies(accepted_quality_modes=supplied)

    assert isinstance(dependencies.accepted_quality_modes, frozenset), (
        dependencies.accepted_quality_modes
    )
    assert dependencies.accepted_quality_modes == frozenset({
        QualityMode.DRAFT_WITHOUT_QA
    }), dependencies.accepted_quality_modes
    with pytest.raises(AttributeError):
        typ.cast("set[QualityMode]", dependencies.accepted_quality_modes).add(
            QualityMode.QA_GATED
        )


def test_the_default_capability_set_is_no_qa_only() -> None:
    """A default ApiDependencies accepts only draft_without_qa."""
    dependencies = ApiDependencies(uow_factory=typ.cast("typ.Any", lambda: None))
    assert dependencies.accepted_quality_modes == frozenset({
        QualityMode.DRAFT_WITHOUT_QA
    }), dependencies.accepted_quality_modes


def test_dataclass_replace_keeps_the_default_no_qa_mode() -> None:
    """Replacing unrelated fields keeps the default capability set."""
    replaced = dc.replace(
        ApiDependencies(uow_factory=typ.cast("typ.Any", lambda: None)),
        upload_max_bytes=1024,
    )
    assert replaced.accepted_quality_modes == frozenset({
        QualityMode.DRAFT_WITHOUT_QA
    }), replaced.accepted_quality_modes
