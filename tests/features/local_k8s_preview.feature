Feature: Local k3d preview CLI

  Scenario: Operators inspect the local preview command surface
    When an operator asks for local preview CLI help
    Then the local preview CLI lists lifecycle commands
    And the up command documents dry-run and image-skip options
