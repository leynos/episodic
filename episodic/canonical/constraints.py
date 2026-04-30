"""Domain-level persistence constraint names shared across adapters."""

UQ_SERIES_PROFILE_HISTORY_REVISION = "uq_series_profile_history_revision"
UQ_EPISODE_TEMPLATE_HISTORY_REVISION = "uq_episode_template_history_revision"
REVISION_CONSTRAINT_NAMES = (
    UQ_SERIES_PROFILE_HISTORY_REVISION,
    UQ_EPISODE_TEMPLATE_HISTORY_REVISION,
)
CK_REFERENCE_BINDINGS_TARGET = "ck_reference_document_bindings_target"
CK_REFERENCE_BINDINGS_EFFECTIVE_EPISODE = (
    "ck_reference_document_bindings_effective_episode"
)
UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE = "uq_ref_doc_bindings_series_rev_effective"
UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE = (
    "uq_ref_doc_bindings_series_rev_no_effective"
)
UQ_REF_DOC_BINDINGS_TEMPLATE_REV = "uq_ref_doc_bindings_template_rev"
UQ_REF_DOC_BINDINGS_JOB_REV = "uq_ref_doc_bindings_job_rev"
