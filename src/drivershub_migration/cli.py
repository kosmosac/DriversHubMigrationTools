"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .assess import assess
from .env import read_env
from .exporter import export_source
from .verify import verify_export


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="drivershub-migrate")
    result.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="configuration file (default: .env)",
    )
    commands = result.add_subparsers(dest="command", required=True)
    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--source",
            help="Hub API base URL; overrides DRIVERSHUB_SOURCE_URL",
        )
        command.add_argument(
            "--output",
            type=Path,
            help="migration directory; overrides DRIVERSHUB_MIGRATION_DIRECTORY",
        )

    assessment = commands.add_parser("assess", help="Assess a source Hub without modifying it")
    common(assessment)
    assessment.add_argument(
        "--no-token",
        action="store_true",
        help="assess public endpoints only",
    )
    export_command = commands.add_parser(
        "export", help="Export currently supported source data"
    )
    common(export_command)
    verify_command = commands.add_parser(
        "verify", help="Verify files and checksums in a migration directory"
    )
    verify_command.add_argument(
        "--output",
        type=Path,
        help="migration directory; overrides DRIVERSHUB_MIGRATION_DIRECTORY",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    file_values = read_env(args.env_file)

    def setting(name: str) -> str | None:
        return os.environ.get(name, file_values.get(name))

    def boolean_setting(name: str, default: bool = False) -> bool:
        value = setting(name)
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise SystemExit(f"{name} must be true or false")

    if args.command == "verify":
        output_value = args.output or setting("DRIVERSHUB_MIGRATION_DIRECTORY")
        if not output_value:
            raise SystemExit(
                "Set DRIVERSHUB_MIGRATION_DIRECTORY in .env or use --output"
            )
        report = verify_export(Path(output_value))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["state"] == "complete" else 1

    if args.command in {"assess", "export"}:
        source = args.source or setting("DRIVERSHUB_SOURCE_URL")
        output_value = args.output or setting("DRIVERSHUB_MIGRATION_DIRECTORY")
        if not source:
            raise SystemExit("Set DRIVERSHUB_SOURCE_URL in .env or use --source")
        if not output_value:
            raise SystemExit(
                "Set DRIVERSHUB_MIGRATION_DIRECTORY in .env or use --output"
            )
        no_token = args.command == "assess" and args.no_token
        token = None if no_token else setting("DRIVERSHUB_APPLICATION_TOKEN")
        if not no_token and not token:
            raise SystemExit(
                "Set DRIVERSHUB_APPLICATION_TOKEN in .env or use --no-token"
            )
        try:
            request_interval = float(setting("DRIVERSHUB_REQUEST_INTERVAL") or "0.6")
        except ValueError as exc:
            raise SystemExit("DRIVERSHUB_REQUEST_INTERVAL must be a number") from exc
        if request_interval < 0:
            raise SystemExit("DRIVERSHUB_REQUEST_INTERVAL must not be negative")
        if args.command == "assess":
            report = assess(
                source,
                Path(output_value),
                token,
                request_interval=request_interval,
            )
        else:
            report = export_source(
                source,
                Path(output_value),
                token,
                request_interval=request_interval,
                allow_source_side_effects=boolean_setting(
                    "DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS"
                ),
            )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
