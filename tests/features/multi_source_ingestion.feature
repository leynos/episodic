Feature: Multi-source ingestion

  Scenario: Ingestion normalizes and merges multiple sources
    Given a series profile "tech-weekly" exists for multi-source ingestion
    And a transcript source is available for multi-source ingestion
    And a brief source is available for multi-source ingestion
    When multi-source ingestion processes the sources
    Then a canonical episode is created for "tech-weekly"
    And source documents are persisted with computed weights
    And conflict resolution metadata is recorded in the approval event
    And TEI header provenance captures source priorities

  Scenario: Single source ingestion requires no conflict resolution
    Given a series profile "solo-show" exists for multi-source ingestion
    And a single transcript source is available for multi-source ingestion
    When multi-source ingestion processes the sources
    Then a canonical episode is created for "solo-show"
    And the single source is marked as preferred
    And TEI header provenance captures source priorities
