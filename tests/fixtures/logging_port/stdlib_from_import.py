"""Fixture importing the stdlib logger factory directly."""

from logging import getLogger

audit = getLogger(__name__)
audit.info("message")
