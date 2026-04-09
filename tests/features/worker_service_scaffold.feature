Feature: Celery worker scaffold

  Scenario: The worker scaffold exposes documented routing and task seams
    Given a worker scaffold environment
    When the Celery worker app is created from environment configuration
    And an operator inspects the worker routing
    And the operator dispatches the representative diagnostic tasks
    Then the I/O-bound task targets the I/O queue and succeeds
    And the CPU-bound task targets the CPU queue and succeeds
    And the worker launch profiles map I/O and CPU workloads to distinct pools
