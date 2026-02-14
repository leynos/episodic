Feature: Canonical repository and unit-of-work behaviour

  Scenario: Repository round-trip persists and retrieves a series profile
    Given a series profile is added via the repository
    When the series profile is fetched by identifier
    Then the fetched profile matches the original

  Scenario: Rolled-back changes are not persisted
    Given a series profile is added but the transaction is rolled back
    When the series profile is fetched by identifier
    Then no series profile is returned

  Scenario: Weight constraint rejects out-of-range values
    Given a canonical episode with supporting entities exists
    When a source document with weight 1.5 is added
    Then the commit fails with an integrity error
