"""Composition-root fixture."""

from tests.fixtures.architecture.composition_root_allows_wiring import api, storage

VALUE = (api.VALUE, storage.VALUE)
