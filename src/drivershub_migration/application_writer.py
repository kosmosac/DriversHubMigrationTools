"""Write exported applications after the basic content stage."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .account_writer import _check_aio_writers, _execute_aio, _execute_mariadb
from .application_import import build_application_stage
from .storage import write_json


def import_applications(directory: Path, target_directory: Path | None, *, mode: str,
                        database: dict[str, object], writers_stopped: bool,
                        runner=subprocess.run) -> dict[str, object]:
    path = directory / "import-journal.json"
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read the import journal") from exc
    stages = journal.get("stages", {})
    if not isinstance(stages, dict) or not isinstance(stages.get("content"), dict) or stages["content"].get("state") != "complete":
        raise ValueError("Import basic content before applications")
    if isinstance(stages.get("applications"), dict) and stages["applications"].get("state") == "complete":
        raise ValueError("The application import is already complete")
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
    sql, summary = build_application_stage(directory)
    stages["applications"] = {**summary, "state": "in-progress"}
    write_json(path, journal)
    try:
        _execute_aio(target, sql, runner) if mode == "aio" else _execute_mariadb(sql, database)
    except ValueError as exc:
        stages["applications"] = {**summary, "state": "failed", "error": str(exc)}
        write_json(path, journal)
        raise
    stages["applications"] = {**summary, "state": "complete"}
    journal["state"] = "partial"
    write_json(path, journal)
    return stages["applications"]
