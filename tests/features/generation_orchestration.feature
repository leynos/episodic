Feature: Structured generation orchestration
  Scenario: Orchestrator plans a structured generation run and executes show notes
    Given a Vidai Mock orchestration server is running
    And a generation orchestration request is prepared
    When the orchestration service plans and executes the request
    Then the orchestration result includes a structured plan and show-notes output
    And the orchestration requests use planning and execution models in order
