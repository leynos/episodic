Feature: Show notes generation from template expansions
  Scenario: Show notes generator extracts topics from a TEI script via a live Vidai Mock server
    Given a Vidai Mock show-notes server is running
    And a TEI script body is prepared for show-notes extraction
    When the show-notes generator processes the script
    Then the generator returns structured show-notes entries
    And the show-notes prompt includes the TEI script body
