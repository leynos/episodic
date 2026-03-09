Feature: OpenAI-compatible LLM adapter
  Scenario: Adapter retries transient failures and sends persisted guardrails
    Given an OpenAI-compatible mock LLM server is running
    And a rendered series prompt and persisted guardrail prompt are available
    When the OpenAI-compatible adapter generates episode content
    Then the adapter retries once and returns the generated text
    And the outbound request includes the persisted guardrail prompt
