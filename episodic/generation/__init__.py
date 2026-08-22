"""Draft-generation, launch, source-limit, and TEI-enrichment services.

``DraftScriptGenerator`` turns bounded canonical sources and presenter context
into a TEI-P5 draft. ``InProcessGenerationRunLauncher`` owns its detached
generation lifecycle and enforces ``GenerationSourceLimits`` before invoking a
provider. The package also exports TEI enrichment services for show notes,
chapter markers, and guest biographies that operate on persisted canonical TEI.
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
    GenerationRunAdmissionError,
    GenerationRunLauncher,
    InProcessGenerationRunLauncher,
)
from episodic.generation.launcher_support import GenerationSourceLimits
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
    "GenerationRunAdmissionError",
    "GenerationRunLauncher",
    "GenerationSourceLimits",
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
