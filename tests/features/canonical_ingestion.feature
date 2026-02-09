Feature: Canonical ingestion

  Scenario: Ingestion job records canonical content
    Given a series profile "science-hour" exists
    And a TEI document titled "Bridgewater" is available
    When an ingestion job records source documents
    Then the canonical episode is stored for "science-hour"
    And the approval state is "draft"
    And an approval event is persisted for the ingestion job
    And source documents are stored and linked to the ingestion job and episode
