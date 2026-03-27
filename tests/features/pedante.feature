Feature: Pedante factuality evaluation
  Scenario: Pedante returns structured findings from a live Vidai Mock server
    Given a Vidai Mock Pedante server is running
    And a TEI-backed Pedante evaluation request is prepared
    When Pedante evaluates the script for factual support
    Then Pedante returns structured findings and normalized usage
    And the Pedante prompt includes TEI XML and cited source packets
