"""Content generation services package.

This package contains services for enriching canonical TEI content with generated
metadata: show notes, chapter markers, guest biographies, and sponsor reads.
"""

from episodic.generation.chapter_markers import (
    ChapterMarker,
    ChapterMarkersGenerator,
    ChapterMarkersGeneratorConfig,
    ChapterMarkersResponseFormatError,
    ChapterMarkersResult,
    enrich_tei_with_chapter_markers,
)
from episodic.generation.guest_bios import (
    GuestBioEntry,
    GuestBiosGenerator,
    GuestBiosGeneratorConfig,
    GuestBioSource,
    GuestBiosResponseFormatError,
    GuestBiosResult,
    enrich_tei_with_guest_bios,
    project_guest_bio_sources,
)
from episodic.generation.show_notes import (
    ShowNotesEntry,
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResponseFormatError,
    ShowNotesResult,
    enrich_tei_with_show_notes,
)

__all__ = [
    "ChapterMarker",
    "ChapterMarkersGenerator",
    "ChapterMarkersGeneratorConfig",
    "ChapterMarkersResponseFormatError",
    "ChapterMarkersResult",
    "GuestBioEntry",
    "GuestBioSource",
    "GuestBiosGenerator",
    "GuestBiosGeneratorConfig",
    "GuestBiosResponseFormatError",
    "GuestBiosResult",
    "ShowNotesEntry",
    "ShowNotesGenerator",
    "ShowNotesGeneratorConfig",
    "ShowNotesResponseFormatError",
    "ShowNotesResult",
    "enrich_tei_with_chapter_markers",
    "enrich_tei_with_guest_bios",
    "enrich_tei_with_show_notes",
    "project_guest_bio_sources",
]
