"""Deterministic pricing engine for cost accounting.

This module provides the pure pricing function used by the ledger recorder.
`PricingEngine` validates that the requested provider operation matches an
immutable `PricingSnapshot`, rejects usage metrics that the snapshot does not
price, and computes integer minor currency units without floating-point
arithmetic.

Example
-------
```python
request = PricingRequest(
    usage={"input_tokens": 100, "output_tokens": 50},
    operation="chat_completions",
)
priced_call = PricingEngine.price(snapshot, request)
```
"""

import dataclasses as dc
import typing as typ

from episodic.cost.ports import (
    OperationMismatchError,
    PricedCall,
    UnknownPricedMetricError,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.cost.pricing_snapshot import PricingSnapshot


@dc.dataclass(frozen=True, slots=True)
class PricingRequest:
    """Input data for one pricing computation passed to `PricingEngine.price`."""

    usage: cabc.Mapping[str, int]
    operation: str
    is_estimated: bool = False


@dc.dataclass(frozen=True, slots=True)
class PricingEngine:
    """Price provider usage from an immutable pricing snapshot."""

    @staticmethod
    def price(
        snapshot: PricingSnapshot,
        request: PricingRequest,
    ) -> PricedCall:
        """Compute integer minor-unit cost for a provider call.

        Parameters
        ----------
        snapshot : PricingSnapshot
            Immutable pricing rates selected for the provider operation.
        request : PricingRequest
            Usage, provider operation, and estimation status for the call.

        Returns
        -------
        PricedCall
            Integer minor-unit cost and currency for the call.

        Raises
        ------
        OperationMismatchError
            If the snapshot operation does not match ``request.operation``.
        UnknownPricedMetricError
            If ``request.usage`` contains a metric absent from the snapshot
            rates.

        Notes
        -----
        Each metric costs ``usage * amount_minor // per_units``. Integer
        division truncates per metric; the rounding policy is recorded per
        ledger row by later roadmap items, never by the snapshot.
        """
        if request.operation != snapshot.operation:
            msg = (
                "pricing snapshot operation does not match requested operation: "
                f"{snapshot.operation!r} != {request.operation!r}"
            )
            raise OperationMismatchError(msg)

        unpriced_metrics = set(request.usage) - set(snapshot.rates)
        if unpriced_metrics:
            joined_metrics = ", ".join(sorted(unpriced_metrics))
            msg = f"usage contains unpriced metrics: {joined_metrics}"
            raise UnknownPricedMetricError(msg)

        computed_cost_minor = sum(
            usage_count
            * snapshot.rates[metric].amount_minor
            // snapshot.rates[metric].per_units
            for metric, usage_count in request.usage.items()
        )
        return PricedCall(
            computed_cost_minor=computed_cost_minor,
            currency=snapshot.currency,
            is_estimated=request.is_estimated,
        )
