Feature: No-QA source-to-script generation slice

  As an integration client
  I want to generate a draft script without QA and download the TEI
  So that I can validate the source-to-script workflow over REST

  Background:
    Given a Vidai Mock inference server is running
    And a series profile exists
    And a host presenter profile and a guest presenter profile are bound

  Scenario: Draft generation without QA produces a downloadable TEI-P5 script
    Given an ingestion job with an attached source document
    When I create a draft-without-qa generation run for the ingested episode
    Then the run creation responds 202 Accepted with a Location header
    And the response carries a Retry-After header
    And the run is created with qa_status "skipped" and my rationale recorded
    When I poll the generation run until it reaches a terminal state
    Then the run status is "succeeded"
    And the event log contains a "tei.persisted" event
    When I fetch the episode TEI as application/tei+xml
    Then the response is a TEI-P5 attachment with qa_status "skipped"
    And the TEI validates against the Episodic TEI-P5 profile

  Scenario: Reusing an idempotency key with the same body replays the run
    Given an ingestion job with an attached source document
    When I create a draft-without-qa run twice with the same idempotency key and body
    Then both responses describe the same run id
    And the replayed response carries the same Location and Retry-After

  Scenario: Reusing an idempotency key with a different body conflicts
    Given an ingestion job with an attached source document
    When I create a draft-without-qa run, then reuse the key with a different rationale
    Then the second response is 409 Conflict

  Scenario: A missing rationale is rejected
    Given an ingestion job with an attached source document
    When I create a draft-without-qa run without a skip_qa_rationale
    Then the response is 400 Bad Request

  Scenario: An unsupported quality mode is unprocessable
    Given an ingestion job with an attached source document
    When I create a generation run with quality_mode "qa_gated"
    Then the response is 422 Unprocessable Entity

  Scenario: Generation failure is reported on the run
    Given an ingestion job with an attached source document
    And the inference server is configured to fail
    When I create a draft-without-qa generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "failed"
    And the run records an error message and an error category

  Scenario: A malformed completion is reported as a failed run
    Given an ingestion job with an attached source document
    And the inference server is configured to return a non-TEI completion
    When I create a draft-without-qa generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "failed"
    And the event log contains a "tei.invalid" event
