"""Forbidden direct femtologging import from an inbound adapter."""

from femtologging import get_logger

logger = get_logger(__name__)
