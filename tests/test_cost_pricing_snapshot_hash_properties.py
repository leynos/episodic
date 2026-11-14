"""Property tests for pricing snapshot determinism.

Satisfies ExecPlan obligation `INV-HASH-DET`: equal snapshot content yields an
equal content hash, independent of mapping insertion order, rate authoring
scale, and instant offset. The classification fixture fails the test if any
`hypothesis.event` class has zero examples, and the seeded negative control
shows that ISO 8601 instant formatting would break the property.
"""

import hashlib
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import assume, event, given, settings

from episodic.cost.pricing_snapshot import PricedService, PricingSnapshot
from episodic.cost.pricing_snapshot_hash import canonical_pricing_document
from episodic.cost.primitives import PricingSourceKind
from episodic.json_canonicalization import canonical_json_bytes
from tests.pricing_snapshot_hash_strategies import SnapshotTwin, snapshot_twin

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_EXPECTED_DETERMINISM_CLASSES = frozenset({
    *(f"service_kind={kind}" for kind in PricedService),
    *(f"source_kind={kind}" for kind in PricingSourceKind),
    "scale=gt1",
    "scale=eq1",
    "offset=utc",
    "offset=non_utc",
})


@st.composite
def _isoformat_case(draw: st.DrawFn) -> SnapshotTwin:
    """Draw a case whose instants are non-UTC or microsecond-bearing."""
    case = draw(snapshot_twin(st.just(value=False)))
    assume(case.offset_minutes != 0 or case.base.retrieved_at.microsecond != 0)
    return case


@st.composite
def _non_utc_case(draw: st.DrawFn) -> SnapshotTwin:
    """Draw a twin whose equivalent instant sits in a non-UTC offset."""
    case = draw(snapshot_twin(st.just(value=False)))
    assume(case.offset_minutes != 0)
    return case


def _hash_document(document: cabc.Mapping[str, object]) -> str:
    """Return the sha256 content hash of a canonical JSON document."""
    return f"sha256:{hashlib.sha256(canonical_json_bytes(document)).hexdigest()}"


def _isoformat_document(snapshot: PricingSnapshot) -> dict[str, object]:
    """Re-encode the canonical document with ISO 8601 instant formatting."""
    document = canonical_pricing_document(snapshot)
    document["retrieved_at"] = snapshot.retrieved_at.isoformat()
    if snapshot.effective_from is not None:
        document["effective_from"] = snapshot.effective_from.isoformat()
    return document


@pytest.fixture(scope="module")
def seen_determinism_classes() -> cabc.Iterator[set[str]]:
    """Fail INV-HASH-DET if a classified class never appears."""
    seen: set[str] = set()
    yield seen
    missing = _EXPECTED_DETERMINISM_CLASSES - seen
    assert not missing, f"INV-HASH-DET never generated: {sorted(missing)}"


@given(case=snapshot_twin(st.just(value=False)))
@settings(max_examples=150, deadline=None)
def test_equal_content_hashes_identically(
    seen_determinism_classes: set[str],
    case: SnapshotTwin,
) -> None:
    """INV-HASH-DET: incidental form never changes the content hash."""
    base, equivalent = case.base, case.equivalent
    scale_class = "gt1" if case.scale_factor > 1 else "eq1"
    offset_class = "utc" if case.offset_minutes == 0 else "non_utc"
    classes = {
        f"service_kind={base.service_kind}",
        f"source_kind={base.source_kind}",
        f"scale={scale_class}",
        f"offset={offset_class}",
    }
    for label in classes:
        event(label)
    seen_determinism_classes.update(classes)

    assert base.content_hash == equivalent.content_hash, (
        "equal content authored differently must hash identically"
    )
    assert canonical_json_bytes(
        canonical_pricing_document(base)
    ) == canonical_json_bytes(canonical_pricing_document(equivalent)), (
        "equal content must also produce identical canonical bytes"
    )


@given(case=_isoformat_case())
@settings(max_examples=100, deadline=None)
def test_isoformat_fault_breaks_canonicalization(case: SnapshotTwin) -> None:
    """INV-HASH-DET negative control: ISO instants change the hash."""
    document = canonical_pricing_document(case.base)
    faulted = _isoformat_document(case.base)
    assert faulted["retrieved_at"] != document["retrieved_at"], (
        "the seeded fault must change the instant encoding"
    )
    if document["effective_from"] is not None:
        assert faulted["effective_from"] != document["effective_from"], (
            "the seeded fault must change the effective-instant encoding"
        )
    assert _hash_document(faulted) != case.base.content_hash, (
        "the ISO-8601 fault must change the hash"
    )


@given(case=_non_utc_case())
@settings(max_examples=100, deadline=None)
def test_isoformat_fault_breaks_offset_independence(case: SnapshotTwin) -> None:
    """INV-HASH-DET negative control: ISO instants break offset independence."""
    assert case.base.content_hash == case.equivalent.content_hash, (
        "the offset pair must be equal content"
    )
    assert _hash_document(_isoformat_document(case.base)) != _hash_document(
        _isoformat_document(case.equivalent)
    ), "the ISO-8601 fault must expose the offset"
