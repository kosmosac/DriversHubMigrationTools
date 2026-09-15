"""Build the baseline delivery import with explicit detail placeholders."""

from __future__ import annotations

from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _records, _timestamp


TRACKER_TYPES = {"tracksim": 2, "trucky": 3, "custom": 4, "unitracker": 5}
DETAIL_MARKER = "migration-import/pending-detail-enrichment"


def _optional_integer(value: object) -> int | None:
    if value in {None, ""}:
        return None
    return _integer(value, "optional integer")


def build_delivery_stage(directory: Path) -> tuple[str, dict[str, object]]:
    deliveries = _records(directory, "deliveries")
    csv_rows = _records(directory, "deliveries-csv")
    csv_by_id: dict[int, dict[str, object]] = {}
    duplicate_csv_rows = 0
    for row in csv_rows:
        logid = _integer(row.get("logid"), "CSV logid")
        if logid in csv_by_id:
            duplicate_csv_rows += 1
        else:
            csv_by_id[logid] = row
    list_ids = {_integer(row.get("logid"), "delivery logid") for row in deliveries}
    csv_only = len(set(csv_by_id) - list_ids)
    missing_csv = 0
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    for row in deliveries:
        logid = _integer(row.get("logid"), "delivery logid")
        user = row.get("user")
        if not isinstance(user, dict):
            raise ValueError(f"Delivery {logid} has invalid user data")
        userid = _integer(user.get("userid"), "delivery userid")
        csv = csv_by_id.get(logid)
        if csv is None:
            missing_csv += 1
            trackerid = None
            tracker_type = 0
        else:
            trackerid = _optional_integer(csv.get(" trackerid"))
            tracker_type = TRACKER_TYPES.get(str(csv.get(" tracker", "")).lower(), 0)
        values = [
            logid, userid, "", row.get("max_speed"),
            _timestamp(row.get("timestamp"), "delivery timestamp"),
            _integer(row.get("status"), "delivery status"), row.get("profit"),
            _integer(row.get("unit"), "delivery unit"), row.get("fuel"),
            row.get("distance"), trackerid, tracker_type,
            _integer(row.get("views"), "delivery views"),
        ]
        statements.append("INSERT INTO `dlog` (`logid`,`userid`,`data`,`topspeed`,`timestamp`,`isdelivered`,`profit`,`unit`,`fuel`,`distance`,`trackerid`,`tracker_type`,`view_count`) VALUES (" + ",".join(_sql_value(value) for value in values) + ");")
        meta = [
            logid,
            row.get("source_city") if isinstance(row.get("source_city"), str) else "",
            row.get("source_company") if isinstance(row.get("source_company"), str) else "",
            row.get("destination_city") if isinstance(row.get("destination_city"), str) else "",
            row.get("destination_company") if isinstance(row.get("destination_company"), str) else "",
            row.get("cargo") if isinstance(row.get("cargo"), str) else "",
            _integer(row.get("cargo_mass"), "delivery cargo mass", optional=True), DETAIL_MARKER,
        ]
        statements.append("INSERT INTO `dlog_meta` (`logid`,`source_city`,`source_company`,`destination_city`,`destination_company`,`cargo_name`,`cargo_mass`,`note`) VALUES (" + ",".join(_sql_value(value) for value in meta) + ");")
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready", "deliveries": len(deliveries),
        "detail_placeholders": len(deliveries), "missing_csv_metadata": missing_csv,
        "duplicate_csv_rows_ignored": duplicate_csv_rows,
        "csv_only_rows_not_imported": csv_only, "detail_marker": DETAIL_MARKER,
        "database_time_zone": "+00:00",
    }
