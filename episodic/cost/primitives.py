"""Leaf cost-accounting primitives shared by ports and domain modules.

Identifiers, the base error type, and the pricing source enumeration are used
by several `episodic.cost` modules. Keeping them in a leaf module lets domain
modules import them without importing the package facade, which composes
application services and therefore must not sit inside the domain boundary.
"""

import enum
import typing as typ

_ISO_CURRENCY_CODE_LENGTH = 3


class PricingSourceKind(enum.StrEnum):
    """Source document type for a pricing snapshot."""

    PROVIDER_RATE_CARD = "provider_rate_card"
    SLA4OAI_PLAN = "sla4oai_plan"


PricingSnapshotId = typ.NewType("PricingSnapshotId", str)
CostLedgerEntryId = typ.NewType("CostLedgerEntryId", str)
IdempotencyKey = typ.NewType("IdempotencyKey", str)
CurrencyCode = typ.NewType("CurrencyCode", str)
BillingPeriodKey = typ.NewType("BillingPeriodKey", str)
MeteringCounterKey = typ.NewType("MeteringCounterKey", str)


class CostAccountingError(Exception):
    """Base exception for cost accounting failures."""


def validate_currency_code(currency: CurrencyCode) -> None:
    """Validate an ISO 4217-style currency code.

    Parameters
    ----------
    currency : CurrencyCode
        Three-letter uppercase currency code to validate.

    Raises
    ------
    ValueError
        If the code is not three alphabetic uppercase characters.

    Examples
    --------
    >>> validate_currency_code(CurrencyCode("USD"))
    """
    currency_value = str(currency)
    if len(currency_value) != _ISO_CURRENCY_CODE_LENGTH or not currency_value.isalpha():
        msg = "currency must be a three-letter ISO 4217 code."
        raise ValueError(msg)
    if currency_value != currency_value.upper():
        msg = "currency must use uppercase ISO 4217 letters."
        raise ValueError(msg)
