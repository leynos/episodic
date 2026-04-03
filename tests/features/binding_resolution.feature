Feature: Reference binding resolution

  Scenario: Editorial team resolves bindings for an episode and snapshots them during ingestion
    Given reference-binding resolution fixtures exist
    And series episodes exist for binding resolution
    And series and template reference bindings exist for binding resolution
    When the editorial team requests the structured brief for the early episode
    And the editorial team requests the resolved bindings for the late episode
    And multi-source ingestion runs with reference bindings
    Then the early-episode brief returns the earlier series revision
    And the late-episode resolved bindings include the latest series revision and the template revision
    And ingestion snapshots the resolved reference documents as source documents
