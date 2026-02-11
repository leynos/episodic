Feature: Schema migration drift detection

  Scenario: No drift when models match migrations
    Given all Alembic migrations have been applied
    When the schema drift check runs
    Then no drift is detected

  Scenario: Drift detected when models diverge from migrations
    Given all Alembic migrations have been applied
    And an unmigrated table has been added to the ORM metadata
    When the schema drift check runs
    Then schema drift is reported
