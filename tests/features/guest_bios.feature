Feature: Guest biography generation from reference document bindings
  Scenario: Guest-bios generator summarizes pinned guest profiles via a live Vidai Mock server
    Given a Vidai Mock guest-bios server is running
    And a TEI script body and pinned guest profile are prepared
    When the guest-bios generator processes the guest profile
    Then the generator returns structured guest biographies
    And the guest-bios prompt includes the pinned guest profile content
    And the enriched TEI contains a guest-bios body block
