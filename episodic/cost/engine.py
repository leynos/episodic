"""Deterministic pricing engine for cost accounting.

This module provides the pure pricing function used by the ledger recorder.
`PricingEngine` validates that the requested provider operation and billing
period match an immutable `PricingSnapshot`, rejects usage metrics that the
snapshot does not price, and computes integer minor currency units without
floating-point arithmetic.

Example
-------
```python
request = PricingRequest(
    usage={"input_tokens": 100, "output_tokens": 50},
    operation="chat_completions",
    billing_period_key=BillingPeriodKey("2026-06"),
)
priced_call = PricingEngine.price(snapshot, request)
```
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from episodic.cost.ports import (
    BillingPeriodKey,
    BillingPeriodMismatchError,
    OperationMismatchError,
    PricedCall,
    PricingSnapshot,
    UnknownPricedMetricError,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_RATE_SCALE = 1_000_000


@dc.dataclass(frozen=True, slots=True)
class PricingRequest:
    """Input data for one pricing computation passed to `PricingEngine.price`."""

    usage: cabc.Mapping[str, int]
    operation: str
    billing_period_key: BillingPeriodKey
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
        usage : Mapping[str, int]
            Canonical usage metrics reported or estimated for one call.
        operation : str
            Provider operation being priced.
        billing_period_key : BillingPeriodKey
            Billing period that must match the pricing snapshot.
        is_estimated : bool, optional
            Whether the usage came from an estimate rather than the provider.

        Returns
        -------
        PricedCall
            Integer minor-unit cost and currency for the call.

        Raises
        ------
        OperationMismatchError
            If the snapshot operation does not match `operation`.
        BillingPeriodMismatchError
            If the snapshot billing period does not match
            `billing_period_key`.
        UnknownPricedMetricError
            If `usage` contains a metric absent from the snapshot rates.

        Notes
        -----
        Rates are stored per one million usage units. Integer division applies
        the current truncation policy; catalogue design owns any future
        fractional-minor-unit rounding policy.
        """
        if request.operation != snapshot.operation:
            msg = (
                "pricing snapshot operation does not match requested operation: "
                f"{snapshot.operation!r} != {request.operation!r}"
            )
            raise OperationMismatchError(msg)
        if request.billing_period_key != snapshot.billing_period_key:
            msg = (
                "pricing snapshot billing period does not match requested "
                f"period: {snapshot.billing_period_key!r} != "
                f"{request.billing_period_key!r}"
            )
            raise BillingPeriodMismatchError(msg)

        unpriced_metrics = set(request.usage) - set(snapshot.rates_minor_per_metric)
        if unpriced_metrics:
            joined_metrics = ", ".join(sorted(unpriced_metrics))
            msg = f"usage contains unpriced metrics: {joined_metrics}"
            raise UnknownPricedMetricError(msg)

        computed_cost_minor = sum(
            usage_count * snapshot.rates_minor_per_metric[metric] // _RATE_SCALE
            for metric, usage_count in request.usage.items()
        )
        return PricedCall(
            computed_cost_minor=computed_cost_minor,
            currency=snapshot.currency,
            is_estimated=request.is_estimated,
        )
