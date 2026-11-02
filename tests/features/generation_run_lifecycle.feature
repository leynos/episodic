Feature: Generation run checkpoint lifecycle

  Scenario: Reviewer approves a checkpoint
    Given a generation run with a created checkpoint
    When the reviewer responds with action "approve"
    Then the checkpoint status becomes "responded"
    And the response payload is recorded

  Scenario: Reviewer cannot respond twice
    Given a checkpoint that has already been responded to
    When the reviewer attempts to respond again
    Then a CheckpointAlreadyTerminal error is raised

  Scenario: A checkpoint times out
    Given a generation run with a created checkpoint
    When the checkpoint times out
    Then the checkpoint status becomes "timed_out"

  Scenario: A checkpoint is cancelled
    Given a generation run with a created checkpoint
    When the checkpoint is cancelled
    Then the checkpoint status becomes "cancelled"

  Scenario: A responded checkpoint survives a new unit of work
    Given a generation run persisted in PostgreSQL
    And a checkpoint created against that run
    When the reviewer responds with action "approve"
    And the unit of work is committed and closed
    Then reading the checkpoint in a new unit of work reports status "responded"
    And the recorded reviewer action is "approve"
