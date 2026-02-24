Feature: Series profile and episode template API

  Scenario: Editorial team manages profile and template revisions
    Given the profile/template API is available
    When a series profile is created through the API
    And an episode template is created for that profile
    And the series profile is updated with optimistic locking
    Then the series profile history contains two revisions
    And a structured brief can be retrieved for downstream generators
