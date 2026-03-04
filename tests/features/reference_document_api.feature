Feature: Reusable reference-document API

  Scenario: Editorial team manages reusable reference documents and bindings
    Given reusable-reference API fixtures exist
    When a host reference document is created
    And the host reference document is updated with optimistic locking
    And two revisions are added for the host reference document
    And the latest revision is bound to the episode template
    Then revision history retrieval returns both revisions
    And stale reference document updates are rejected
    And host and guest documents are accessed through series-aligned paths
