"""Write durable user state after the account import."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .account_writer import _check_aio_writers, _execute_aio, _execute_mariadb
from .storage import write_json
from .user_state_import import build_user_state_stage


def import_user_state(directory: Path, target_directory: Path | None, *, mode: str, database: dict[str, object], approved: bool, backup_confirmed: bool, writers_stopped: bool, convert_personal_notes_to_global: bool = False, runner=subprocess.run) -> dict[str, object]:
    if not approved or not backup_confirmed:
        raise ValueError("The user-state import requires --approve and --backup-confirmed")
    journal_path = directory / "import-journal.json"
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read the import journal") from exc
    stages = journal.get("stages", {})
    if not isinstance(stages, dict) or not isinstance(stages.get("accounts"), dict) or stages["accounts"].get("state") != "complete":
        raise ValueError("Import accounts before user state")
    if isinstance(stages.get("user_state"), dict) and stages["user_state"].get("state") == "complete":
        raise ValueError("The user-state import is already complete")
    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        target = target_directory.resolve()
        _check_aio_writers(target, runner)
    elif mode == "mariadb":
        if not writers_stopped:
            raise ValueError("Direct MariaDB mode requires --writers-stopped")
        target = None
    else:
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")
    sql, summary = build_user_state_stage(
        directory,
        convert_personal_notes_to_global=convert_personal_notes_to_global,
    )
    stages["user_state"] = {**summary, "state": "in-progress"}
    write_json(journal_path, journal)
    try:
        _execute_aio(target, sql, runner) if mode == "aio" else _execute_mariadb(sql, database)
    except ValueError as exc:
        stages["user_state"] = {**summary, "state": "failed", "error": str(exc)}
        write_json(journal_path, journal)
        raise
    stages["user_state"] = {**summary, "state": "complete"}
    journal["state"] = "partial"
    write_json(journal_path, journal)
    return stages["user_state"]
