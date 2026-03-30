Feature: Falcon HTTP service scaffold
  Scenario: Granian serves the Falcon health endpoints
    Given a Granian Falcon HTTP service is running
    When an operator checks the health endpoints
    Then the liveness endpoint reports that the application is up
    And the readiness endpoint reports that the database is ready
