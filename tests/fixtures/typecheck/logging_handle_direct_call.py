"""Negative typing fixture for the logging-port direct-call boundary."""

from episodic.logging import get_logger


def direct_logger_call_is_not_permitted() -> None:
    """Demonstrate the rejected raw logger method surface."""
    logger = get_logger(__name__)
    logger.info("This call must remain a type error.")
