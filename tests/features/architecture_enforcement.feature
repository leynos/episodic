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

  Scenario: A clean orchestration fixture passes
    Given the architecture fixture package "orchestration_node_imports_port"
    When the architecture checker runs
    Then the architecture check passes

  Scenario: A LangGraph node importing an adapter is rejected
    Given the architecture fixture package "orchestration_node_imports_outbound_adapter"
    When the architecture checker runs
    Then the architecture check fails
    And the architecture diagnostic mentions "ARCH001"
    And the architecture diagnostic mentions "orchestration._graph_nodes"

  Scenario: A Celery task importing an adapter is rejected
    Given the architecture fixture package "celery_task_imports_inbound_adapter"
    When the architecture checker runs
    Then the architecture check fails
    And the architecture diagnostic mentions "ARCH001"
    And the architecture diagnostic mentions "worker.tasks"

  Scenario: A checkpoint payload importing storage is rejected
    Given the architecture fixture package "checkpoint_payload_imports_storage"
    When the architecture checker runs
    Then the architecture check fails
    And the architecture diagnostic mentions "ARCH001"
    And the architecture diagnostic mentions "orchestration._checkpoint_payload"
