"""Write remaining standard-plugin resources."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .account_writer import _check_aio_writers, _execute_aio, _execute_mariadb
from .economy_inventory_import import build_economy_inventory_stage
from .poll_task_import import build_poll_task_stage
from .storage import write_json


def _write_stage(directory: Path, target_directory: Path | None, *, name: str, prerequisite: str, builder, mode: str, database: dict[str, object], approved: bool, backup_confirmed: bool, writers_stopped: bool, runner=subprocess.run) -> dict[str, object]:
    if not approved or not backup_confirmed:
        raise ValueError(f"The {name} import requires --approve and --backup-confirmed")
    path = directory / "import-journal.json"
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read the import journal") from exc
    stages = journal.get("stages", {})
    if not isinstance(stages, dict) or not isinstance(stages.get(prerequisite), dict) or stages[prerequisite].get("state") != "complete":
        raise ValueError(f"Complete {prerequisite} before {name}")
    if isinstance(stages.get(name), dict) and stages[name].get("state") == "complete":
        raise ValueError(f"The {name} import is already complete")
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
    sql, summary = builder(directory)
    stages[name] = {**summary, "state": "in-progress"}
    journal["state"] = "partial"
    journal.pop("final_verification", None)
    write_json(path, journal)
    try:
        _execute_aio(target, sql, runner) if mode == "aio" else _execute_mariadb(sql, database)
    except ValueError as exc:
        stages[name] = {**summary, "state": "failed", "error": str(exc)}
        write_json(path, journal)
        raise
    stages[name] = {**summary, "state": "complete"}
    write_json(path, journal)
    return stages[name]


def import_polls_tasks(directory: Path, target_directory: Path | None, **kwargs) -> dict[str, object]:
    return _write_stage(directory, target_directory, name="polls_tasks", prerequisite="events_challenges", builder=build_poll_task_stage, **kwargs)


def import_economy_inventory(directory: Path, target_directory: Path | None, **kwargs) -> dict[str, object]:
    return _write_stage(directory, target_directory, name="economy_inventory", prerequisite="economy", builder=build_economy_inventory_stage, **kwargs)
