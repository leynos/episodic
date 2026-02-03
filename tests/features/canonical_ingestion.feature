Feature: Canonical ingestion

  Scenario: Ingestion job records canonical content
    Given a series profile "science-hour" exists
    And a TEI document titled "Bridgewater" is available
    When an ingestion job records source documents
    Then the canonical episode is stored for "science-hour"
    And the approval state is "draft"
