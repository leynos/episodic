"""Shared constants and aliases for chapter-marker generation modules."""

import re

from episodic.logging import get_logger

type JsonMapping = dict[str, object]

logger = get_logger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "The assistant acts as a podcast chapter-marker generator. Given a TEI P5 "
    "podcast script and segment-transition metadata, create playback chapter "
    "markers aligned to segment starts. Return JSON only with key "
    '"chapters". Each chapter must include "title" and "start". The "start" '
    "value must be a non-negative ISO 8601-style duration in the form "
    "PT#H#M#S with integer hours, minutes, and seconds only (for example: "
    "PT0S, PT5M30S, PT1H2M3S). Days and fractional units are not allowed. "
    "Optional fields: summary, end, duration, and tei_locator."
)

_SUPPORTED_DURATION_MESSAGE = (
    "must be a non-negative ISO 8601-style duration in the form PT#H#M#S "
    "with integer hours, minutes, and seconds only."
)

_EMPTY_CHAPTER_SUMMARY_SENTINEL_PREFIX = "__EPISODIC_EMPTY_CHAPTER_SUMMARY_"

_ISO_8601_DURATION_PATTERN = re.compile(
    r"^P(?=.*\d[HMS])T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?$"
)
