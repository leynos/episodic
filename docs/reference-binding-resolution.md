# Reference binding resolution developer guide

## Overview

This document describes the developer-facing APIs for reference binding
resolution, which powers the structured brief and resolved-bindings endpoints.
These APIs enable episode-aware resolution of reference documents, selecting
the appropriate revision based on `effective_from_episode_id` precedence.

## Core Functions

### `resolve_bindings()`

**Location:** `episodic/canonical/reference_documents/resolution.py`

Resolves reference bindings for a series profile context, applying
episode-aware precedence logic for series-profile bindings while merging
template bindings without filtering.

### `resolve_bindings()` Usage

- Building a structured brief for episode generation
- Resolving reference documents for ingestion workflows
- Fetching all applicable reference documents for a series/template combination

### `resolve_bindings()` Arguments

Table: Parameters for `resolve_bindings()`

| Parameter           | Type                  | Description                                             |
| ------------------- | --------------------- | ------------------------------------------------------- |
| `uow`               | `CanonicalUnitOfWork` | Unit of work for database access                        |
| `series_profile_id` | `uuid.UUID`           | The series profile identifier                           |
| `template_id`       | `uuid.UUID or None`   | Optional episode template for merging template bindings |
| `episode_id`        | `uuid.UUID or None`   | Optional episode for episode-aware precedence           |

### `resolve_bindings()` Result

`list[ResolvedBinding]`: Resolved bindings with their revisions and documents.

### `resolve_bindings()` Behavior

1. **Validation**: If `episode_id` is provided, validates that the episode
   exists and belongs to the series profile. If `template_id` is provided,
   validates that the template exists and belongs to the series profile.

2. **Binding Collection**: Collects all series-profile bindings and optionally
   template bindings (if `template_id` is valid).

3. **Resolution**:
   - Without `episode_id`: Returns all bindings without filtering
   - With `episode_id`: Applies episode-aware precedence to series-profile
     bindings (selects the binding with the latest `effective_from_episode_id`
     that is on or before the target episode's created_at), merges template
     bindings without filtering

### `resolve_bindings()` Example

```python
from episodic.canonical.reference_documents import resolve_bindings

async with SqlAlchemyUnitOfWork(session_factory) as uow:
    resolved = await resolve_bindings(
        uow,
        series_profile_id=profile_id,
        template_id=template_id,
        episode_id=episode_id,
    )
    for binding in resolved:
        print(f"Document: {binding.document.kind}")
        print(f"Revision: {binding.revision.content_hash}")
```

______________________________________________________________________

### `snapshot_resolved_bindings()`

**Location:** `episodic/canonical/reference_documents/snapshots.py`

Persists resolved bindings as provenance source documents, creating a snapshot
of which reference documents were used at a specific point in time.

### `snapshot_resolved_bindings()` Usage

- Ingestion workflows that need to record which reference documents were used
- Audit trails for episode generation
- Provenance tracking for canonical content

### `snapshot_resolved_bindings()` Arguments

Table: Parameters for `snapshot_resolved_bindings()`

| Parameter  | Type                    | Description                               |
| ---------- | ----------------------- | ----------------------------------------- |
| `uow`      | `CanonicalUnitOfWork`   | Unit of work for database access          |
| `resolved` | `list[ResolvedBinding]` | The already-resolved bindings to snapshot |
| `context`  | `SnapshotContext`       | Snapshot metadata passed to the function  |

Table: Fields for `SnapshotContext` used by `snapshot_resolved_bindings()`

| Field                  | Type                | Description                                      |
| ---------------------- | ------------------- | ------------------------------------------------ |
| `ingestion_job_id`     | `uuid.UUID`         | The ingestion job identifier                     |
| `canonical_episode_id` | `uuid.UUID or None` | Optional associated episode                      |
| `created_at`           | `datetime or None`  | Optional timestamp; defaults to current UTC time |

### `snapshot_resolved_bindings()` Result

`list[SourceDocument]`: The created source document entities.

### `snapshot_resolved_bindings()` Example

```python
from episodic.canonical.reference_documents import (
    resolve_bindings,
    snapshot_resolved_bindings,
)

async with SqlAlchemyUnitOfWork(session_factory) as uow:
    resolved = await resolve_bindings(uow, ...)
    source_docs = await snapshot_resolved_bindings(
        uow,
        resolved=resolved,
        context=SnapshotContext(
            ingestion_job_id=job_id,
            canonical_episode_id=episode_id,
        ),
    )
```

Legacy keyword arguments such as `ingestion_job_id`, `canonical_episode_id`,
and `created_at` are no longer accepted directly by
`snapshot_resolved_bindings()`. Callers must pass a `SnapshotContext` instance
instead.

______________________________________________________________________

### `serialize_resolved_binding()`

**Location:** `episodic/api/serializers.py`

Serializes a `ResolvedBinding` to a JSON-serializable dictionary for API
responses. The output includes the complete binding, revision, and document
information.

### `serialize_resolved_binding()` Usage

- Building API responses for resolved-bindings endpoints
- Serializing binding data for JSON output

### `serialize_resolved_binding()` Arguments

Table: Parameters for `serialize_resolved_binding()`

| Parameter          | Type              | Description                       |
| ------------------ | ----------------- | --------------------------------- |
| `resolved_binding` | `ResolvedBinding` | The resolved binding to serialize |

### `serialize_resolved_binding()` Result

`dict[str, Any]`: A dictionary with three keys:

- `binding`: The serialized `ReferenceBinding`
- `revision`: The serialized `ReferenceDocumentRevision`
- `document`: The serialized `ReferenceDocument`

### `serialize_resolved_binding()` Output Structure

```json
{
  "binding": {
    "id": "uuid-string",
    "reference_document_revision_id": "uuid-string",
    "target_kind": "series_profile|episode_template|ingestion_job",
    "series_profile_id": "uuid-string|null",
    "episode_template_id": "uuid-string|null",
    "ingestion_job_id": "uuid-string|null",
    "effective_from_episode_id": "uuid-string|null",
    "created_at": "ISO-8601-timestamp"
  },
  "revision": {
    "id": "uuid-string",
    "reference_document_id": "uuid-string",
    "content": {},
    "content_hash": "string",
    "author": "string",
    "change_note": "string",
    "created_at": "ISO-8601-timestamp"
  },
  "document": {
    "id": "uuid-string",
    "owner_series_profile_id": "uuid-string",
    "kind": "style_guide|host_profile|guest_profile|...",
    "lifecycle_state": "active|archived|...",
    "metadata": {},
    "lock_version": 1,
    "created_at": "ISO-8601-timestamp",
    "updated_at": "ISO-8601-timestamp"
  }
}
```

### `serialize_resolved_binding()` Example

```python
from episodic.api.serializers import serialize_resolved_binding

for resolved in resolved_bindings:
    payload = serialize_resolved_binding(resolved)
    # payload is ready for JSON serialization
```

## Data Types

### `ResolvedBinding`

**Location:** `episodic/canonical/reference_documents/resolution.py`

A dataclass that holds a resolved binding triple:

```python
@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    binding: ReferenceBinding
    revision: ReferenceDocumentRevision
    document: ReferenceDocument
```

This encapsulates the complete context for a resolved reference: which binding
was selected, which revision it points to, and the parent document metadata.

## Episode-Aware Resolution Algorithm

When `episode_id` is provided, the resolution algorithm works as follows:

1. **Group by Document**: Series-profile bindings are grouped by their parent
   reference document ID.

2. **Collect Applicable Episodes**: For each binding with an
   `effective_from_episode_id`, fetch the corresponding episode if it exists
   and its `created_at` is on or before the target episode's `created_at`.

3. **Select Best Binding**: For each document group:
   - If there are applicable episode bindings, select the one with the latest
     episode `created_at` (ties broken by binding `created_at`, then binding `id`)
   - Otherwise, select the default binding (no `effective_from_episode_id`)
     with the latest `created_at` (ties broken by `id`)

4. **Merge Template Bindings**: Template bindings are always included without
   episode filtering (domain invariant: template bindings never have
   `effective_from_episode_id`).

## Error Handling

### `resolve_bindings()` Errors

- If `episode_id` is provided, but the episode doesn't exist or doesn't belong
  to the series profile, returns an empty list
- If `template_id` is provided, but the template doesn't exist or doesn't belong
  to the series profile, template bindings are skipped

### `snapshot_resolved_bindings()` Errors

- Persists only the already-resolved bindings it is given
- Relies on the unit-of-work and database layers to surface integrity errors
  during flush or commit

## Testing

### Unit Tests

See `tests/test_serializers.py` for unit tests of
`serialize_resolved_binding()`.

### Integration Tests

See `tests/test_binding_resolution_api.py` for integration tests covering:

- Episode-aware binding resolution
- Cross-profile validation (episode ownership)
- Template validation
- Error handling for invalid/missing parameters

## Related Documentation

- Architecture Decision Record (ADR-001): Reference binding resolution
  algorithm design
- API documentation for `/series-profiles/{profile_id}/brief`
- API documentation for `/series-profiles/{profile_id}/resolved-bindings`
