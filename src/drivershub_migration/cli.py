"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .assess import assess
from .env import read_env


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="drivershub-migrate")
    result.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="configuration file (default: .env)",
    )
    commands = result.add_subparsers(dest="command", required=True)
    assessment = commands.add_parser("assess", help="Assess a source Hub without modifying it")
    assessment.add_argument(
        "--source",
        help="Hub API base URL; overrides DRIVERSHUB_SOURCE_URL",
    )
    assessment.add_argument(
        "--output",
        type=Path,
        help="migration directory; overrides DRIVERSHUB_MIGRATION_DIRECTORY",
    )
    assessment.add_argument(
        "--no-token",
        action="store_true",
        help="assess public endpoints only",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    file_values = read_env(args.env_file)

    def setting(name: str) -> str | None:
        return os.environ.get(name, file_values.get(name))

    if args.command == "assess":
        source = args.source or setting("DRIVERSHUB_SOURCE_URL")
        output_value = args.output or setting("DRIVERSHUB_MIGRATION_DIRECTORY")
        if not source:
            raise SystemExit("Set DRIVERSHUB_SOURCE_URL in .env or use --source")
        if not output_value:
            raise SystemExit(
                "Set DRIVERSHUB_MIGRATION_DIRECTORY in .env or use --output"
            )
        token = None if args.no_token else setting("DRIVERSHUB_APPLICATION_TOKEN")
        if not args.no_token and not token:
            raise SystemExit(
                "Set DRIVERSHUB_APPLICATION_TOKEN in .env or use --no-token"
            )
        report = assess(source, Path(output_value), token)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
