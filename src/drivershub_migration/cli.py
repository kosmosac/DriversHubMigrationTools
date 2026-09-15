"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .assess import assess
from .account_writer import import_accounts
from .application_writer import import_applications
from .configuration_writer import import_configuration
from .content_writer import import_content
from .delivery_writer import import_deliveries
from .user_state_writer import import_user_state
from .env import read_env
from .event_challenge_writer import import_events_challenges
from .exporter import export_source
from .dry_run import create_import_dry_run
from .economy_writer import import_economy
from .import_plan import create_import_plan
from .output import (
    render_assessment,
    render_export,
    render_import_plan,
    render_import_dry_run,
    render_target_preflight,
    render_verification,
)
from .relationship_writer import import_relationships
from .final_verification import verify_target
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
    result.add_argument(
        "--json",
        action="store_true",
        help="write the complete machine-readable report to standard output",
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
        "plan-import", help="Create a non-writing destination import plan"
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
    dry_run_command = commands.add_parser(
        "dry-run-import", help="Plan destination writes without modifying the destination"
    )
    dry_run_command.add_argument(
        "--output",
        type=Path,
        help="migration directory; overrides DRIVERSHUB_MIGRATION_DIRECTORY",
    )
    account_command = commands.add_parser(
        "import-accounts", help="Import accounts into a stopped destination"
    )
    account_command.add_argument("--output", type=Path)
    account_command.add_argument("--target", type=Path)
    account_command.add_argument("--approve", action="store_true")
    account_command.add_argument("--backup-confirmed", action="store_true")
    account_command.add_argument("--writers-stopped", action="store_true")
    configuration_command = commands.add_parser(
        "import-configuration",
        help="Import portable configuration and branding into a stopped destination",
    )
    configuration_command.add_argument("--output", type=Path)
    configuration_command.add_argument("--target", type=Path)
    configuration_command.add_argument("--config-path", type=Path)
    configuration_command.add_argument("--approve", action="store_true")
    configuration_command.add_argument("--backup-confirmed", action="store_true")
    configuration_command.add_argument("--writers-stopped", action="store_true")
    user_state_command = commands.add_parser(
        "import-user-state", help="Import notes, bans, and role history"
    )
    user_state_command.add_argument("--output", type=Path)
    user_state_command.add_argument("--target", type=Path)
    user_state_command.add_argument("--approve", action="store_true")
    user_state_command.add_argument("--backup-confirmed", action="store_true")
    user_state_command.add_argument("--writers-stopped", action="store_true")
    content_command = commands.add_parser(
        "import-content", help="Import self-contained Hub content"
    )
    content_command.add_argument("--output", type=Path)
    content_command.add_argument("--target", type=Path)
    content_command.add_argument("--approve", action="store_true")
    content_command.add_argument("--backup-confirmed", action="store_true")
    content_command.add_argument("--writers-stopped", action="store_true")
    applications_command = commands.add_parser(
        "import-applications", help="Import application records"
    )
    applications_command.add_argument("--output", type=Path)
    applications_command.add_argument("--target", type=Path)
    applications_command.add_argument("--approve", action="store_true")
    applications_command.add_argument("--backup-confirmed", action="store_true")
    applications_command.add_argument("--writers-stopped", action="store_true")
    event_command = commands.add_parser(
        "import-events-challenges", help="Import event and challenge definitions"
    )
    event_command.add_argument("--output", type=Path)
    event_command.add_argument("--target", type=Path)
    event_command.add_argument("--approve", action="store_true")
    event_command.add_argument("--backup-confirmed", action="store_true")
    event_command.add_argument("--writers-stopped", action="store_true")
    economy_command = commands.add_parser(
        "import-economy", help="Import losslessly recoverable economy state"
    )
    economy_command.add_argument("--output", type=Path)
    economy_command.add_argument("--target", type=Path)
    economy_command.add_argument("--approve", action="store_true")
    economy_command.add_argument("--backup-confirmed", action="store_true")
    economy_command.add_argument("--writers-stopped", action="store_true")
    delivery_command = commands.add_parser(
        "import-deliveries", help="Import baseline delivery history"
    )
    delivery_command.add_argument("--output", type=Path)
    delivery_command.add_argument("--target", type=Path)
    delivery_command.add_argument("--approve", action="store_true")
    delivery_command.add_argument("--backup-confirmed", action="store_true")
    delivery_command.add_argument("--writers-stopped", action="store_true")
    relationship_command = commands.add_parser(
        "import-relationships", help="Import delivery-dependent relationships"
    )
    relationship_command.add_argument("--output", type=Path)
    relationship_command.add_argument("--target", type=Path)
    relationship_command.add_argument("--approve", action="store_true")
    relationship_command.add_argument("--backup-confirmed", action="store_true")
    relationship_command.add_argument("--writers-stopped", action="store_true")
    final_command = commands.add_parser(
        "verify-target", help="Verify the completed import in the stopped destination"
    )
    final_command.add_argument("--output", type=Path)
    final_command.add_argument("--target", type=Path)
    final_command.add_argument("--writers-stopped", action="store_true")
    dry_run_command.add_argument(
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
        print(
            json.dumps(report, indent=2, ensure_ascii=False)
            if args.json
            else (
                render_verification(report)
                if args.command == "verify"
                else render_import_plan(report, Path(output_value))
            )
        )
        if args.command == "verify":
            return 0 if report["integrity"] == "valid" and report["export"] == "complete" else 1
        return 0 if report["state"] == "complete" else 1

    if args.command in {
        "preflight-target",
        "dry-run-import",
        "import-accounts",
        "import-configuration",
        "import-user-state",
        "import-content",
        "import-applications",
        "import-events-challenges",
        "import-economy",
        "import-deliveries",
        "import-relationships",
        "verify-target",
    }:
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
            if args.command == "import-accounts":
                report = import_accounts(
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
                    approved=args.approve,
                    backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-configuration":
                report = import_configuration(
                    Path(output_value),
                    Path(target_value) if target_value else None,
                    args.config_path or (
                        Path(value)
                        if (value := setting("DRIVERSHUB_TARGET_CONFIG_PATH"))
                        else None
                    ),
                    mode=target_mode,
                    database={
                        "host": setting("DRIVERSHUB_TARGET_DB_HOST"),
                        "port": setting("DRIVERSHUB_TARGET_DB_PORT"),
                        "user": setting("DRIVERSHUB_TARGET_DB_USER"),
                        "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"),
                        "database": setting("DRIVERSHUB_TARGET_DB_NAME"),
                        "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET"),
                    },
                    approved=args.approve,
                    backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-user-state":
                report = import_user_state(
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
                    approved=args.approve,
                    backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-content":
                report = import_content(
                    Path(output_value), Path(target_value) if target_value else None,
                    mode=target_mode,
                    database={
                        "host": setting("DRIVERSHUB_TARGET_DB_HOST"),
                        "port": setting("DRIVERSHUB_TARGET_DB_PORT"),
                        "user": setting("DRIVERSHUB_TARGET_DB_USER"),
                        "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"),
                        "database": setting("DRIVERSHUB_TARGET_DB_NAME"),
                        "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET"),
                    },
                    approved=args.approve,
                    backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-applications":
                report = import_applications(
                    Path(output_value), Path(target_value) if target_value else None,
                    mode=target_mode,
                    database={
                        "host": setting("DRIVERSHUB_TARGET_DB_HOST"),
                        "port": setting("DRIVERSHUB_TARGET_DB_PORT"),
                        "user": setting("DRIVERSHUB_TARGET_DB_USER"),
                        "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"),
                        "database": setting("DRIVERSHUB_TARGET_DB_NAME"),
                        "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET"),
                    },
                    approved=args.approve,
                    backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-events-challenges":
                report = import_events_challenges(
                    Path(output_value), Path(target_value) if target_value else None,
                    mode=target_mode,
                    database={
                        "host": setting("DRIVERSHUB_TARGET_DB_HOST"), "port": setting("DRIVERSHUB_TARGET_DB_PORT"),
                        "user": setting("DRIVERSHUB_TARGET_DB_USER"), "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"),
                        "database": setting("DRIVERSHUB_TARGET_DB_NAME"), "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET"),
                    }, approved=args.approve, backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-economy":
                report = import_economy(
                    Path(output_value), Path(target_value) if target_value else None,
                    mode=target_mode,
                    database={"host": setting("DRIVERSHUB_TARGET_DB_HOST"), "port": setting("DRIVERSHUB_TARGET_DB_PORT"), "user": setting("DRIVERSHUB_TARGET_DB_USER"), "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"), "database": setting("DRIVERSHUB_TARGET_DB_NAME"), "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET")},
                    approved=args.approve, backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-deliveries":
                report = import_deliveries(
                    Path(output_value), Path(target_value) if target_value else None,
                    mode=target_mode,
                    database={"host": setting("DRIVERSHUB_TARGET_DB_HOST"), "port": setting("DRIVERSHUB_TARGET_DB_PORT"), "user": setting("DRIVERSHUB_TARGET_DB_USER"), "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"), "database": setting("DRIVERSHUB_TARGET_DB_NAME"), "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET")},
                    approved=args.approve, backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "import-relationships":
                report = import_relationships(
                    Path(output_value), Path(target_value) if target_value else None,
                    mode=target_mode,
                    database={"host": setting("DRIVERSHUB_TARGET_DB_HOST"), "port": setting("DRIVERSHUB_TARGET_DB_PORT"), "user": setting("DRIVERSHUB_TARGET_DB_USER"), "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"), "database": setting("DRIVERSHUB_TARGET_DB_NAME"), "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET")},
                    approved=args.approve, backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
            elif args.command == "verify-target":
                report = verify_target(
                    Path(output_value), Path(target_value) if target_value else None,
                    mode=target_mode,
                    database={"host": setting("DRIVERSHUB_TARGET_DB_HOST"), "port": setting("DRIVERSHUB_TARGET_DB_PORT"), "user": setting("DRIVERSHUB_TARGET_DB_USER"), "password": setting("DRIVERSHUB_TARGET_DB_PASSWORD"), "database": setting("DRIVERSHUB_TARGET_DB_NAME"), "unix_socket": setting("DRIVERSHUB_TARGET_DB_UNIX_SOCKET")},
                    writers_stopped=args.writers_stopped,
                )
            else:
                function = preflight_target if args.command == "preflight-target" else create_import_dry_run
                report = function(
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
        if args.command == "import-accounts":
            accounts = report["stages"]["accounts"]
            print("Account import complete.")
            print(f"Imported accounts: {accounts.get('inserted_accounts', 0)}")
            print(f"Merged accounts: {accounts.get('merged_accounts', 0)}")
            print("Next: keep destination writer services stopped for the remaining import stages.")
            return 0
        if args.command == "import-configuration":
            print("Configuration import complete.")
            print(f"Portable backend values: {report.get('portable_backend_values', 0)}")
            print(f"Branding assets: {report.get('branding_assets', 0)}")
            print("Destination infrastructure and integration settings retained: yes")
            print("Next: keep destination writer services stopped for the remaining import stages.")
            return 0
        if args.command == "import-user-state":
            print("User-state import complete.")
            print(f"Global notes: {report.get('global_notes', 0)}")
            print(f"Role-history records: {report.get('role_history_records', 0)}")
            print(f"Active bans: {report.get('active_bans', 0)}")
            print(f"Ban-history records: {report.get('ban_history_records', 0)}")
            print(f"Personal administrator notes skipped: {report.get('personal_notes_skipped', 0)}")
            print("Next: keep destination writer services stopped for the remaining import stages.")
            return 0
        if args.command == "import-content":
            print("Content import complete.")
            for name, count in report.get("resources", {}).items():
                print(f"{name.replace('_', ' ').title()}: {count}")
            print("Next: keep destination writer services stopped for the remaining import stages.")
            return 0
        if args.command == "import-applications":
            print("Application import complete.")
            print(f"Applications: {report.get('applications', 0)}")
            print(f"Pending applications: {report.get('pending_applications', 0)}")
            print("Next: keep destination writer services stopped for the remaining import stages.")
            return 0
        if args.command == "import-events-challenges":
            print("Event and challenge import complete.")
            print(f"Challenges: {report.get('challenges', 0)}")
            print(f"Events: {report.get('events', 0)}")
            print(f"Events with unavailable original creator: {report.get('event_creators_unavailable', 0)}")
            print(f"Challenge delivery links deferred: {report.get('challenge_delivery_links_deferred', 0)}")
            print("Next: keep destination writer services stopped for the remaining import stages.")
            return 0
        if args.command == "import-economy":
            print("Economy import complete.")
            print(f"Balances: {report.get('balances', 0)}")
            print(f"Transactions: {report.get('transactions', 0)}")
            print(f"Transactions pending optional enrichment: {report.get('transactions_pending_enrichment', 0)}")
            print(f"Transactions without identifiable parties: {report.get('transactions_without_identifiable_party', 0)}")
            print("Missing source timestamps and internal metadata use recognizable placeholders.")
            print("Next: keep destination writer services stopped for the remaining import stages.")
            return 0
        if args.command == "import-deliveries":
            print("Baseline delivery import complete.")
            print(f"Deliveries: {report.get('deliveries', 0)}")
            print(f"Detail placeholders: {report.get('detail_placeholders', 0)}")
            print(f"Deliveries without CSV metadata: {report.get('missing_csv_metadata', 0)}")
            print(f"Duplicate CSV rows ignored: {report.get('duplicate_csv_rows_ignored', 0)}")
            print(f"CSV-only rows without safe timestamps not imported: {report.get('csv_only_rows_not_imported', 0)}")
            print("Next: keep destination writer services stopped while relationships are imported.")
            return 0
        if args.command == "import-relationships":
            print("Relationship import complete.")
            print(f"Challenge delivery links: {report.get('challenge_delivery_links', 0)}")
            print(f"Challenge completions: {report.get('challenge_completions', 0)}")
            print(f"Pending division requests: {report.get('pending_division_requests', 0)}")
            print("Next: keep destination writer services stopped until final verification completes.")
            return 0
        if args.command == "verify-target":
            print("Destination verification complete.")
            print(f"State: {report.get('state')}")
            print(f"Verified resource counts: {len(report.get('expected', {}))}")
            print(f"Count mismatches: {len(report.get('count_mismatches', []))}")
            print(f"Referential-integrity violations: {len(report.get('integrity_violations', {}))}")
            if report.get("state") == "complete":
                print("Next: restart the destination Hub and perform the post-import checks below.")
                return 0
            print("Do not restart destination writer services; inspect target-verification.json.")
            return 1
        print(
            json.dumps(report, indent=2, ensure_ascii=False)
            if args.json
            else (
                render_target_preflight(report)
                if args.command == "preflight-target"
                else render_import_dry_run(report, Path(output_value))
            )
        )
        if args.command == "preflight-target":
            return 0 if report["state"] in {"complete", "action-required"} else 1
        return 0 if report["state"] == "ready" else 1

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
        print(
            json.dumps(report, indent=2, ensure_ascii=False)
            if args.json
            else (
                render_assessment(report, Path(output_value))
                if args.command == "assess"
                else render_export(report, Path(output_value))
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
