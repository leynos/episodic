"""Fixture using the stdlib logging module under an alias."""

import logging as audit

logger = audit.getLogger(__name__)
logger.info("message")
