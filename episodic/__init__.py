"""Episodic application package.

Episodic generates and curates podcast episode content from canonical source
material. The package is organised along hexagonal boundaries so that domain
logic stays independent of the transports and infrastructure around it.

Subpackages
-----------
``episodic.api``
    Transport-facing HTTP integration: Falcon resources, request and response
    serialisation, authorization, and error envelopes.
``episodic.canonical``
    Domain services and persistence adapters for canonical content, including
    the SQLAlchemy storage layer and its unit of work.
``episodic.orchestration``
    Coordination of generation workflows, including checkpointing and the
    structured generation run lifecycle.

This module deliberately performs no runtime imports so that importing
``episodic`` stays cheap and free of side effects.
"""
