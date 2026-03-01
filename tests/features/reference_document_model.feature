Feature: Reusable reference-document model alignment

  Scenario: Structured brief includes bound host and guest reference documents
    Given a series profile and episode template exist
    And host and guest reference revisions are bound to the profile and template
    When the structured brief is retrieved for the profile and template
    Then the structured brief includes host and guest reference documents
