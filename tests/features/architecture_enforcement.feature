Feature: Architecture enforcement

  Scenario: A violating domain module is rejected with a clear diagnostic
    Given the architecture fixture package "domain_imports_storage"
    When the architecture checker runs
    Then the architecture check fails
    And the architecture diagnostic mentions "ARCH001"
    And the architecture diagnostic mentions "domain"
    And the architecture diagnostic mentions "storage"

  Scenario: A violating inbound adapter is rejected with a clear diagnostic
    Given the architecture fixture package "api_imports_outbound_adapter"
    When the architecture checker runs
    Then the architecture check fails
    And the architecture diagnostic mentions "ARCH001"
    And the architecture diagnostic mentions "api"
    And the architecture diagnostic mentions "storage"

  Scenario: A composition root that wires adapters is accepted
    Given the architecture fixture package "composition_root_allows_wiring"
    When the architecture checker runs
    Then the architecture check passes
