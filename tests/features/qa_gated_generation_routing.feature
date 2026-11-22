Feature: QA-gated generation routing

  As an integration client
  I want QA-gated runs to pass through evaluation before any draft is saved
  So that only QA-passed scripts are persisted while no-QA drafts keep their direct route

  Background:
    Given a Vidai Mock inference server is running
    And a series profile exists
    And a host presenter profile and a guest presenter profile are bound

  Scenario: A QA-gated run whose evaluators pass persists a QA-passed draft
    Given QA evaluation is configured with a passing evaluator
    And an ingestion job with an attached source document
    When I create a qa-gated generation run for the ingested episode
    Then the run creation responds 202 Accepted with a Location header
    And the run is created with qa_status "pending" and no skip rationale
    When I poll the generation run until it reaches a terminal state
    Then the run status is "succeeded" with qa_status "passed"
    And the event log records "qa.evaluation_started", "qa.result" and "tei.persisted" in order
    When I fetch the episode TEI as JSON
    Then the envelope reports quality_mode "qa_gated" and qa_status "passed"

  Scenario: A QA-gated run whose evaluators fail escalates without persisting a draft
    Given QA evaluation is configured with a failing evaluator
    And an ingestion job with an attached source document
    When I create a qa-gated generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "failed" with qa_status "failed"
    And the run records the error category "qa.escalation_required"
    And the event log contains a "qa.escalated" event and no "tei.persisted" event
    And the episode TEI is not found

  Scenario: A QA-gated run with a skip rationale is rejected
    Given QA evaluation is configured with a passing evaluator
    And an ingestion job with an attached source document
    When I create a qa-gated generation run with a skip_qa_rationale
    Then the response is 400 Bad Request with constraint "exclusive_with_quality_mode"

  Scenario: QA-gated runs are unprocessable when no evaluators are configured
    Given no QA evaluators are configured
    And an ingestion job with an attached source document
    When I create a qa-gated generation run for the ingested episode
    Then the response is 422 Unprocessable Entity

  Scenario: A draft-without-QA run still takes the direct route when evaluators exist
    Given QA evaluation is configured with a failing evaluator
    And an ingestion job with an attached source document
    When I create a draft-without-qa generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "succeeded" with qa_status "skipped"
    And the event log contains no "qa.evaluation_started" event