"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .assess import assess
from .env import read_env
from .exporter import export_source
from .import_plan import create_import_plan
from .target import preflight_target
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
    plan_command = commands.add_parser(
        "plan-import", help="Create a non-writing destination identity plan"
    )
    plan_command.add_argument(
        "--output",
        type=Path,
        help="migration directory; overrides DRIVERSHUB_MIGRATION_DIRECTORY",
    )
    target_command = commands.add_parser(
        "preflight-target", help="Inspect a destination without modifying it"
    )
    target_command.add_argument(
        "--output",
        type=Path,
        help="migration directory; overrides DRIVERSHUB_MIGRATION_DIRECTORY",
    )
    target_command.add_argument(
        "--target",
        type=Path,
        help="Docker AIO directory; overrides DRIVERSHUB_TARGET_DIRECTORY",
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

    def progress(message: str) -> None:
        print(f"[drivershub-migrate] {message}", file=sys.stderr, flush=True)

    if args.command in {"verify", "plan-import"}:
        output_value = args.output or setting("DRIVERSHUB_MIGRATION_DIRECTORY")
        if not output_value:
            raise SystemExit(
                "Set DRIVERSHUB_MIGRATION_DIRECTORY in .env or use --output"
            )
        try:
            report = (
                verify_export(Path(output_value))
                if args.command == "verify"
                else create_import_plan(Path(output_value))
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if args.command == "verify":
            return 0 if report["integrity"] == "valid" else 1
        return 0 if report["state"] == "complete" else 1

    if args.command == "preflight-target":
        output_value = args.output or setting("DRIVERSHUB_MIGRATION_DIRECTORY")
        target_mode = (setting("DRIVERSHUB_TARGET_MODE") or "aio").lower()
        target_value = args.target or setting("DRIVERSHUB_TARGET_DIRECTORY")
        if not output_value:
            raise SystemExit(
                "Set DRIVERSHUB_MIGRATION_DIRECTORY in .env or use --output"
            )
        if target_mode == "aio" and not target_value:
            raise SystemExit("Set DRIVERSHUB_TARGET_DIRECTORY in .env or use --target")
        try:
            report = preflight_target(
                Path(output_value),
                Path(target_value) if target_value else None,
                mode=target_mode,
                database={
                    "host": setting("DRIVERSHUB_TARGET_DB_HOST"),
                    "port": setting("DRIVERSHUB_TARGET_DB_PORT"),
                    "user": setting("DRIVERSHUB_TARGET_DB_USER"),
                    "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"),
                    "database": setting("DRIVERSHUB_TARGET_DB_NAME"),
                    "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET"),
                },
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["state"] in {"complete", "action-required"} else 1

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
            request_interval = float(setting("DRIVERSHUB_REQUEST_INTERVAL") or "1.1")
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
                progress=progress,
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
                allow_delivery_view_updates=boolean_setting(
                    "DRIVERSHUB_ALLOW_DELIVERY_VIEW_UPDATES"
                ),
                progress=progress,
            )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
