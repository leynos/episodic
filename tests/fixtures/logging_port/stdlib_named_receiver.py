"""Fixture using a non-conventional local name for the stdlib logger."""

import logging as logging_module

audit = logging_module.getLogger(__name__)
audit.info("message")
