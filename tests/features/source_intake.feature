Feature: Source intake API

  Scenario: Editorial team uploads and attaches source material
    Given source-intake API fixtures exist
    When an editor uploads source material and attaches it to a new ingestion job
    Then the ingestion job is ready for generation
    And repeated upload requests replay the stored response
    And changed upload bodies with the same idempotency key conflict
