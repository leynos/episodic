"""The ``episodic`` command-line interface.

``main`` is re-exported here because the ``episodic`` console script declared
in ``[project.scripts]`` targets ``episodic.cli:main``.
"""

from episodic.cli.entrypoint import main

__all__ = ["main"]
