"""Errors raised while loading a file-backed pricing catalogue."""


class PricingCatalogueError(ValueError):
    """Raised when a pricing card cannot be loaded or is ambiguous.

    The message always names the offending file so an operator can find it.
    """
