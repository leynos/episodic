"""Content generation services package.

This package contains services for enriching canonical TEI content with generated
metadata: show notes, chapter markers, guest biographies, and sponsor reads.
"""

from episodic.generation.show_notes import (
    ShowNotesEntry,
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResponseFormatError,
    ShowNotesResult,
    enrich_tei_with_show_notes,
)

__all__ = [
    "ShowNotesEntry",
    "ShowNotesGenerator",
    "ShowNotesGeneratorConfig",
    "ShowNotesResponseFormatError",
    "ShowNotesResult",
    "enrich_tei_with_show_notes",
]
