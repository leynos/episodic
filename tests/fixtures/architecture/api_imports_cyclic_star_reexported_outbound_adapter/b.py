"""Cyclic star barrel that forwards exports from module a."""

from .a import *  # noqa: F403  # The fixture deliberately exercises architecture analysis of star re-exports.
