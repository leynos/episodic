Feature: Immutable pricing snapshots
  Pricing snapshots are immutable, content-addressed documents, so historical
  run costs remain reproducible after rate cards change.

  Scenario: A pinned run reprices identically after its rate card is revised
    Given a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    And a generation run pinned to that rate card
    When the run records a call with 1000000 input tokens and 1000000 cached input tokens
    And the rate card file is revised to charge 7.5 minor units per million cached input tokens
    Then the run's ledger entry costs 23 minor units
    And repricing the ledger entry from its persisted snapshot costs 23 minor units
    And a new run pinned after the revision prices the same usage at 22 minor units

  Scenario: A pinned run keeps pricing after its rate card file is deleted
    Given a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    And a generation run pinned to that rate card
    When the rate card file is deleted
    And the run records a call with 1000000 input tokens and 1000000 cached input tokens
    Then the run's ledger entry costs 23 minor units

  Scenario: A text-to-speech rate card prices characters and audio duration
    Given a TTS rate card charging 1500 minor units per 1000000 input characters
    And the TTS rate card charges 5 minor units per 60000 output audio milliseconds
    When the rate card is persisted and read back
    Then the stored snapshot equals the rate card
    And usage of 2000000 input characters and 120000 output audio milliseconds costs 3010 minor units

  Scenario: A helper-service SLA4OAI plan document is preserved
    Given an SLA4OAI plans document for the helper service "pedante"
    When the helper pricing snapshot is persisted and read back
    Then the stored source document text is identical to the original
    And changing one character of the document produces a different content hash

  Scenario: A tampered pricing snapshot row is refused
    Given a persisted gpt-4o-mini pricing snapshot
    When its rates are altered directly in the database
    Then reading the snapshot fails with a pricing snapshot integrity error

  Scenario: A Vidai Mock completion is priced from the persisted snapshot
    Given a Vidai Mock server reporting 2000000 prompt tokens of which 1000000 are cached and 500000 completion tokens
    And a generation run pinned to a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    When the run completes a chat completion through the OpenAI-compatible adapter and records its cost
    Then the run's ledger entry costs 53 minor units
    When the rate card file is revised to charge 7.5 minor units per million cached input tokens
    Then repricing the ledger entry from its persisted snapshot costs 53 minor units
    And a new run pinned after the revision prices the same usage at 52 minor units
