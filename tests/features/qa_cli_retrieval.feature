Feature: QA artefact retrieval through the CLI

  The CLI is an HTTP client, so these scenarios drive the real command against
  the real application rather than a stub of either.

  Background:
    Given a canonical episode with a generated TEI draft
    And a recorded Pedante evaluation with 3 findings, one of them blocking
    And a recorded Chrono evaluation with a runtime estimate and no findings
    And a recorded Anthem evaluation that failed to execute

  Scenario: Listing evaluations in table form
    When the operator lists the episode's QA evaluations
    Then the CLI exits with status 0
    And the table lists 3 evaluations newest first
    And the summary line reports "3 of 3 evaluations"

  Scenario: Listing evaluations as JSON
    When the operator lists the episode's QA evaluations as JSON
    Then the CLI exits with status 0
    And the JSON total is 3
    And the JSON lists 3 evaluations newest first

  Scenario: Filtering evaluations by evaluator
    When the operator lists the episode's QA evaluations for evaluator "pedante"
    Then the CLI exits with status 0
    And the table lists 1 evaluation
    And every table row names evaluator "pedante"
    And the summary line reports "1 of 1 evaluations"

  Scenario: Combining filters that match nothing
    When the operator lists the episode's QA evaluations for evaluator "chrono" with compliance status "non_compliant"
    Then the CLI exits with status 0
    And the summary line reports "0 of 0 evaluations"

  Scenario: Hiding another principal's evaluations
    When a different principal lists the episode's QA evaluations
    Then the CLI exits with status 1
    And the CLI reports "404"

  Scenario: Naming the missing credential
    When the operator lists the episode's QA evaluations without a token
    Then the CLI exits with status 1
    And the CLI reports "EPISODIC_API_TOKEN"