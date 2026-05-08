Feature: Chrono spoken-runtime estimation
  Scenario: Chrono estimates spoken runtime from TEI dialogue
    Given a TEI-backed Chrono evaluation request is prepared
    When Chrono estimates the spoken runtime
    Then Chrono returns estimated seconds and estimator metadata
