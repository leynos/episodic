"""Command-line wiring for architecture enforcement."""

import argparse
import sys
from pathlib import Path

from .checker import check_architecture
from .policy import default_policy, fixture_policy


def main(argv: list[str] | None = None) -> int:
    """Run the architecture checker from the command line."""
    parser = argparse.ArgumentParser(
        description="Check Episodic hexagonal architecture import boundaries."
    )
    parser.add_argument("--root", default="episodic", help="Package root to scan.")
    parser.add_argument("--package", default="episodic", help="Import package name.")
    parser.add_argument(
        "--fixture-policy",
        action="store_true",
        help="Use the generic fixture policy for architecture BDD fixtures.",
    )
    args = parser.parse_args(argv)

    policy = fixture_policy(args.package) if args.fixture_policy else default_policy()
    result = check_architecture(
        package_root=Path(args.root),
        package=args.package,
        policy=policy,
    )
    for violation in result.violations:
        print(violation.render(), file=sys.stderr)
    return 0 if result.ok else 1
