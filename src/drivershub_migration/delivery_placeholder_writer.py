"""Repair empty baseline delivery placeholders created by older tool versions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .account_import import _sql_value
from .account_writer import _check_aio_writers, _execute_aio, _execute_mariadb
from .delivery_import import DETAIL_MARKER, placeholder_detail
from .storage import write_json


def repair_delivery_placeholders(directory: Path, target_directory: Path | None, *, mode: str, database: dict[str, object], approved: bool, backup_confirmed: bool, writers_stopped: bool, runner=subprocess.run) -> dict[str, object]:
    if not approved or not backup_confirmed:
        raise ValueError("The placeholder repair requires --approve and --backup-confirmed")
    journal_path = directory / "import-journal.json"
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read the import journal") from exc
    deliveries = journal.get("stages", {}).get("deliveries", {})
    if not isinstance(deliveries, dict) or deliveries.get("state") != "complete":
        raise ValueError("Import deliveries before repairing their placeholders")
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

    variants = {
        (1, 1): placeholder_detail(delivered=True, ats=False),
        (1, 2): placeholder_detail(delivered=True, ats=True),
        (2, 1): placeholder_detail(delivered=False, ats=False),
        (2, 2): placeholder_detail(delivered=False, ats=True),
    }
    cases = " ".join(
        f"WHEN d.`isdelivered`={status} AND d.`unit`={unit} THEN {_sql_value(payload)}"
        for (status, unit), payload in variants.items()
    )
    sql = (
        "START TRANSACTION;\n"
        "UPDATE `dlog` d JOIN `dlog_meta` m ON m.`logid`=d.`logid` "
        f"SET d.`data`=CASE {cases} ELSE {_sql_value(variants[(1, 1)])} END "
        f"WHERE d.`data`='' AND m.`note`={_sql_value(DETAIL_MARKER)};\n"
        "SELECT ROW_COUNT();\nCOMMIT;\n"
    )
    # Execute the narrowly scoped update. The count is derived from the journal,
    # because the shared writer intentionally does not expose SELECT output.
    _execute_aio(target, sql, runner) if mode == "aio" else _execute_mariadb(sql, database)
    repaired = int(deliveries.get("detail_placeholders", 0))
    stage = {"state": "complete", "eligible_placeholders": repaired, "detail_marker": DETAIL_MARKER}
    journal["delivery_placeholder_repair"] = stage
    # A previous final verification predates this repair and must be repeated.
    journal["state"] = "partial"
    journal.pop("final_verification", None)
    write_json(journal_path, journal)
    return stage
