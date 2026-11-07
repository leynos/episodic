Feature: QA artefact persistence and retrieval

  Background:
    Given a canonical episode with a generated TEI draft
    And a recorded Pedante evaluation with 3 findings, one of them blocking
    And a recorded Chrono evaluation with a runtime estimate and no findings
    And a recorded Anthem evaluation that failed to execute

  Scenario: Retrieving every QA evaluation for an episode over HTTP
    When the owner requests the episode's QA evaluations
    Then the response lists 3 evaluations ordered newest first
    And each evaluation reports its evaluator and compliance status

  Scenario: The listed finding count matches the detail representation
    When the owner requests the episode's QA evaluations
    And the owner requests each listed evaluation by identifier
    Then every listed finding count equals the number of findings in its detail response

  Scenario: Filtering QA evaluations by evaluator over HTTP
    When the owner requests the episode's QA evaluations for evaluator "pedante"
    Then the response lists 1 evaluation
    And the evaluation's evaluator is "pedante"

  Scenario: Filtering QA evaluations by compliance status over HTTP
    When the owner requests the episode's QA evaluations with compliance status "non_compliant"
    Then the response lists 1 evaluation
    And the evaluation's compliance status is "non_compliant"

  Scenario: Combining evaluator and compliance filters over HTTP
    When the owner requests the episode's QA evaluations for evaluator "chrono" with compliance status "non_compliant"
    Then the response lists 0 evaluations
    And the response reports a total of 0

  Scenario: Retrieving one QA evaluation with its findings
    When the owner requests the recorded Pedante evaluation by identifier
    Then the response includes the evaluation summary
    And the response includes 3 findings ordered as the evaluator emitted them
    And each finding includes its remediation guidance

  Scenario: A different principal cannot read another owner's QA evaluations
    When a different principal requests the episode's QA evaluations
    Then the response status is 404
    And the error code is "qa_evaluation_not_found"

  Scenario: Rejecting an unknown evaluator filter
    When the owner requests the episode's QA evaluations for evaluator "nonsuch"
    Then the response status is 400
    And the error code is "validation_error"
    And the error details name the "evaluator" field

  Scenario: A successful evaluation supersedes an earlier errored one
    When the Anthem evaluation is recorded again with a successful outcome
    And the owner requests the episode's QA evaluations for evaluator "anthem"
    Then the response lists 1 evaluation
    And the evaluation's compliance status is "compliant"