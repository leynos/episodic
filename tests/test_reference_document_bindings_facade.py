"""Regression tests for the reference-document bindings façade."""

from episodic.canonical import reference_documents
from episodic.canonical.reference_documents import (
    _binding_creation,
    _binding_queries,
    bindings,
)


def test_bindings_facade_reexports_public_entry_points() -> None:
    """Expose the focused binding submodule functions through the façade."""
    assert bindings.create_reference_binding is (
        _binding_creation.create_reference_binding
    )
    assert bindings.get_reference_binding is _binding_queries.get_reference_binding
    assert bindings.list_reference_bindings is (
        _binding_queries.list_reference_bindings
    )
    assert bindings.list_reference_bindings_paged is (
        _binding_queries.list_reference_bindings_paged
    )
    assert set(bindings.__all__) == {
        "create_reference_binding",
        "get_reference_binding",
        "list_reference_bindings",
        "list_reference_bindings_paged",
    }


def test_reference_documents_package_uses_bindings_facade() -> None:
    """Keep package-level imports aligned with the bindings façade."""
    assert reference_documents.create_reference_binding is (
        bindings.create_reference_binding
    )
    assert reference_documents.get_reference_binding is bindings.get_reference_binding
    assert reference_documents.list_reference_bindings is (
        bindings.list_reference_bindings
    )
    assert reference_documents.list_reference_bindings_paged is (
        bindings.list_reference_bindings_paged
    )
