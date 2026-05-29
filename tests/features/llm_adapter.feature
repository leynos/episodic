Feature: OpenAI-compatible LLM adapter
  Scenario: Adapter retries transient failures and sends persisted guardrails
    Given an OpenAI-compatible mock LLM server is running
    And a rendered series prompt and persisted guardrail prompt are available
    When the OpenAI-compatible adapter generates episode content
    Then the adapter retries once and returns the generated text
    And the outbound request includes the persisted guardrail prompt

  Scenario: Adapter applies a configured chars-per-token ratio for token estimation
    Given an OpenAI-compatible mock LLM server is running without transient failures
    And a rendered series prompt and persisted guardrail prompt are available
    When the OpenAI-compatible adapter generates content with a custom chars-per-token ratio
    Then the adapter returns the generated text on the first attempt
