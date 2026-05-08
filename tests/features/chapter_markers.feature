Feature: Chapter marker generation aligned to script segments
  Scenario: Chapter marker generator creates chapters from a TEI script via a live Vidai Mock server
    Given a Vidai Mock chapter-marker server is running
    And a TEI script body is prepared for chapter-marker extraction
    When the chapter-marker generator processes the script
    Then the generator returns structured chapter markers
    And the chapter-marker prompt includes the TEI script and segment metadata
