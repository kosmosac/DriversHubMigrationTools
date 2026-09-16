"""High-level resumable export and import workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .account_writer import import_accounts
from .additional_writer import import_economy_inventory, import_polls_tasks
from .application_writer import import_applications
from .configuration_writer import import_configuration
from .content_writer import import_content
from .delivery_writer import import_deliveries
from .dry_run import create_import_dry_run
from .economy_writer import import_economy
from .event_challenge_writer import import_events_challenges
from .exporter import export_source
from .final_verification import verify_target
from .import_plan import create_import_plan
from .relationship_writer import import_relationships
from .user_state_writer import import_user_state
from .verify import verify_export


def export_all(
    source: str,
    directory: Path,
    token: str,
    *,
    request_interval: float,
    export_delivery_details: bool,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    if progress:
        progress("Assessing the source and exporting all supported data")
    export_source(
        source, directory, token,
        request_interval=request_interval,
        export_delivery_details=export_delivery_details,
        progress=progress,
    )
    if progress:
        progress("Verifying the completed migration directory")
    verification = verify_export(directory)
    return {
        "state": (
            "complete"
            if verification.get("integrity") == "valid"
            and verification.get("export") == "complete"
            else "incomplete"
        ),
        "verification": verification,
    }


def _journal_stages(directory: Path) -> dict[str, object]:
    path = directory / "import-journal.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        stages = value.get("stages", {})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise ValueError("Unable to read the import journal") from exc
    if not isinstance(stages, dict):
        raise ValueError("The import journal has no stages object")
    return stages


def _complete(directory: Path, stage: str) -> bool:
    value = _journal_stages(directory).get(stage, {})
    return isinstance(value, dict) and value.get("state") == "complete"


def import_all(
    directory: Path,
    target_directory: Path | None,
    *,
    mode: str,
    database: dict[str, object],
    config_path: Path | None,
    backup_confirmed: bool,
    writers_stopped: bool,
    convert_personal_notes: bool,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    if not _complete(directory, "accounts"):
        if progress:
            progress("Creating the destination import plan")
        plan = create_import_plan(directory)
        if plan.get("state") != "complete":
            raise ValueError("The import plan contains unresolved identity conflicts")
        if not backup_confirmed:
            raise ValueError("Starting a writing import requires --backup-confirmed")
        if progress:
            progress("Running destination preflight and full rollback validation")
        dry_run = create_import_dry_run(
            directory, target_directory, mode=mode, database=database,
            config_path=config_path,
            convert_personal_notes=convert_personal_notes,
            writers_stopped=writers_stopped,
        )
        if dry_run.get("state") != "ready":
            validation = dry_run.get("database_validation", {})
            error = validation.get("error") if isinstance(validation, dict) else None
            raise ValueError(f"The full import validation is blocked: {error or 'inspect import-dry-run.json'}")
        if progress:
            progress("Importing accounts")
        import_accounts(
            directory, target_directory, mode=mode, database=database,
            backup_confirmed=backup_confirmed, writers_stopped=writers_stopped,
        )

    stages = (
        (
            "configuration",
            lambda: import_configuration(
                directory, target_directory, config_path, mode=mode,
                database=database, writers_stopped=writers_stopped,
            ),
        ),
        (
            "user_state",
            lambda: import_user_state(
                directory, target_directory, mode=mode, database=database,
                writers_stopped=writers_stopped,
                convert_personal_notes_to_global=convert_personal_notes,
            ),
        ),
        ("content", lambda: import_content(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
        ("applications", lambda: import_applications(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
        ("events_challenges", lambda: import_events_challenges(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
        ("polls_tasks", lambda: import_polls_tasks(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
        ("economy", lambda: import_economy(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
        ("economy_inventory", lambda: import_economy_inventory(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
        ("deliveries", lambda: import_deliveries(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
        ("relationships", lambda: import_relationships(directory, target_directory, mode=mode, database=database, writers_stopped=writers_stopped)),
    )
    for name, function in stages:
        if _complete(directory, name):
            if progress:
                progress(f"Skipping completed import stage: {name}")
            continue
        if progress:
            progress(f"Running import stage: {name}")
        function()

    if progress:
        progress("Verifying the complete destination import")
    verification = verify_target(
        directory, target_directory, mode=mode, database=database,
        writers_stopped=writers_stopped,
    )
    return {"state": verification.get("state"), "verification": verification}
