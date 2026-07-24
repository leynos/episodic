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
from episodic.generation.draft_script import (
    DraftPresenterProfile,
    DraftScriptGenerationError,
    DraftScriptGenerator,
    DraftScriptProviderResponseError,
    DraftScriptRequest,
    DraftScriptResponseFormatError,
    DraftScriptResult,
    DraftScriptSource,
    DraftScriptTeiError,
    DraftScriptTokenBudgetError,
    DraftScriptTransientProviderError,
    DraftTurn,
    LLMDraftScriptGenerator,
    LLMDraftScriptGeneratorConfig,
)
from episodic.generation.guest_bios import (
    GuestBioEntry,
    GuestBiosEnrichmentRequest,
    GuestBiosEnrichmentResult,
    GuestBiosGenerator,
    GuestBiosGeneratorConfig,
    GuestBioSource,
    GuestBiosResponseFormatError,
    GuestBiosResult,
    enrich_tei_with_guest_bios,
    generate_guest_bios_from_reference_bindings,
    project_guest_bio_sources,
)
from episodic.generation.launcher import (
    GenerationRunLauncher,
    InProcessGenerationRunLauncher,
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
    "DraftPresenterProfile",
    "DraftScriptGenerationError",
    "DraftScriptGenerator",
    "DraftScriptProviderResponseError",
    "DraftScriptRequest",
    "DraftScriptResponseFormatError",
    "DraftScriptResult",
    "DraftScriptSource",
    "DraftScriptTeiError",
    "DraftScriptTokenBudgetError",
    "DraftScriptTransientProviderError",
    "DraftTurn",
    "GenerationRunLauncher",
    "GuestBioEntry",
    "GuestBioSource",
    "GuestBiosEnrichmentRequest",
    "GuestBiosEnrichmentResult",
    "GuestBiosGenerator",
    "GuestBiosGeneratorConfig",
    "GuestBiosResponseFormatError",
    "GuestBiosResult",
    "InProcessGenerationRunLauncher",
    "LLMDraftScriptGenerator",
    "LLMDraftScriptGeneratorConfig",
    "ShowNotesEntry",
    "ShowNotesGenerator",
    "ShowNotesGeneratorConfig",
    "ShowNotesResponseFormatError",
    "ShowNotesResult",
    "enrich_tei_with_chapter_markers",
    "enrich_tei_with_guest_bios",
    "enrich_tei_with_show_notes",
    "generate_guest_bios_from_reference_bindings",
    "project_guest_bio_sources",
]
