"""Property tests for PyPy-backed Pylint object building."""

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from tests.test_pylint_pypy_helpers import (
    ObjectBuildScenario,
    load_pylint_pypy_module,
    make_routing_spies,
    run_object_builder,
    setup_fake_dependencies,
)


@given(
    st.lists(
        st.one_of(st.integers(), st.floats(), st.binary(), st.none()),
        min_size=1,
        max_size=5,
    )
)
def test_non_string_dir_entries_are_ignored(
    non_strings: list[object],
) -> None:
    """Non-string entries returned from ``dir()`` are ignored."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        module = load_pylint_pypy_module(monkeypatch)
        scenario = ObjectBuildScenario()

        def fake_dir(obj: object) -> list[object]:
            return [*non_strings, "ordinary"]

        spies = make_routing_spies(scenario)
        setup_fake_dependencies(monkeypatch, module, spies)
        monkeypatch.setattr(module, "dir", fake_dir, raising=False)

        run_object_builder(module, scenario.builder, scenario.node, scenario.target)

        assert "ordinary" in scenario.node.locals
        for alias in non_strings:
            assert alias not in scenario.node.locals


@given(st.sampled_from([AttributeError, TypeError]))
def test_getattr_failures_signal_skip(
    exc_type: type[Exception],
) -> None:
    """Getattr-style failures produce a skip and dummy attachment."""
    assert issubclass(exc_type, (AttributeError, TypeError))
    with pytest.MonkeyPatch.context() as monkeypatch:
        module = load_pylint_pypy_module(monkeypatch)
        scenario = ObjectBuildScenario()

        def fake_resolve_member(
            node_arg: object,
            obj: object,
            alias: str,
        ) -> tuple[object | None, bool, bool]:
            if alias == "missing":
                return None, False, True
            return object(), False, False

        def fake_dir(obj: object) -> list[str]:
            return ["missing"]

        spies = make_routing_spies(scenario)
        setup_fake_dependencies(monkeypatch, module, spies)
        monkeypatch.setattr(module, "_resolve_member", fake_resolve_member)
        monkeypatch.setattr(module, "dir", fake_dir, raising=False)

        run_object_builder(module, scenario.builder, scenario.node, scenario.target)

        assert spies.attach_calls == [(scenario.node, "missing")]
