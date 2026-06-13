Feature: Source intake API

  Scenario: Editorial team uploads and attaches source material
    Given source-intake API fixtures exist
    When an editor uploads source material and attaches it to a new ingestion job
    Then the ingestion job is ready for generation
    And repeated upload requests replay the stored response
    And changed upload bodies with the same idempotency key conflict

  Scenario: Upload content type is rejected
    Given source-intake API fixtures exist
    When an editor uploads source material with an unsupported content type
    Then the source-intake API rejects the request with "unsupported_content_type"

  Scenario: Upload payload is too large
    Given source-intake API fixtures exist
    When an editor uploads source material larger than the configured cap
    Then the source-intake API rejects the request with "payload_too_large"

  Scenario: Source attachment discriminator is invalid
    Given source-intake API fixtures exist
    When an editor attaches source material with an unknown discriminator
    Then the source-intake API rejects the request with "source_payload_invalid"

  Scenario: Source attachment references a missing job
    Given source-intake API fixtures exist
    When an editor attaches source material to a missing ingestion job
    Then the source-intake API rejects the request with "ingestion_job_not_found"

  Scenario: Source attachment references a missing upload
    Given source-intake API fixtures exist
    When an editor attaches a missing upload to a new ingestion job
    Then the source-intake API rejects the request with "upload_not_found"

  Scenario: Source attachment references an upload that is not ready
    Given source-intake API fixtures exist
    When an editor attaches a pending upload to a new ingestion job
    Then the source-intake API rejects the request with "upload_not_ready"

  Scenario: Editorial team lists attached source material
    Given source-intake API fixtures exist
    When an editor lists source material attached to a new ingestion job
    Then the source-intake API returns the attached source material
