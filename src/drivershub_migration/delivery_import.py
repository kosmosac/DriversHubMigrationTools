"""Build the baseline delivery import with explicit detail placeholders."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _records, _timestamp
from .storage import TRACKER_TYPES, compress_and_encode


DETAIL_MARKER = "migration-import/pending-detail-enrichment"


def _compressed_json(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return compress_and_encode(raw)


def _compressed_text(value: str) -> str:
    return compress_and_encode(value.encode())


def placeholder_detail(*, delivered: bool, ats: bool) -> str:
    """Return a backend-compatible, frontend-renderable placeholder payload."""
    event_type = "job.delivered" if delivered else "job.cancelled"
    unavailable = {"name": "Migration data unavailable", "unique_id": "migration-placeholder"}
    detail = {
        "object": "event",
        "type": event_type,
        "data": {"object": {
            "driver": {},
            "events": [{
                "type": event_type,
                "real_time": "1970-01-01T00:00:00Z",
                "meta": {"distance": 0, "revenue": 0, "autoParked": False},
            }],
            "game": {
                "short_name": "ats" if ats else "eut2",
                "had_police_enabled": False,
            },
            "start_time": "1970-01-01T00:00:00Z",
            "stop_time": "1970-01-01T00:00:00Z",
            "source_city": unavailable,
            "source_company": unavailable,
            "destination_city": unavailable,
            "destination_company": unavailable,
            "cargo": {**unavailable, "mass": 0, "damage": 0},
            "truck": {
                "brand": {"name": "Migration placeholder"},
                "name": "Details unavailable",
                "unique_id": "migration-placeholder",
                "license_plate_country": None,
                "license_plate": "N/A",
                "initial_odometer": 0,
                "odometer": 0,
                "top_speed": 0,
                "average_speed": 0,
            },
            "trailers": [{
                "brand": None, "name": "Migration data unavailable",
                "license_plate_country": None, "license_plate": "N/A",
            }],
            "planned_distance": 0,
            "driven_distance": 0,
            "fuel_used": 0,
            "adblue_used": 0,
            "is_special": False,
            "is_late": False,
            "market": "freight_market",
            "multiplayer": None,
        }},
    }
    return _compressed_json(detail)


def exported_detail(value: object, logid: int) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"Delivery {logid} has invalid exported detail data")
    detail = copy.deepcopy(value)
    try:
        obj = detail["data"]["object"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Delivery {logid} has incomplete exported detail data") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"Delivery {logid} has invalid exported detail object")
    # GET /dlog/{id} removes this field before returning the payload. Restore an
    # empty value because the destination endpoint performs the same deletion.
    obj.setdefault("driver", {})
    return _compressed_json(detail)


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
    details = _records(directory, "deliveries-details")
    detail_by_id = {
        _integer(row.get("logid"), "delivery detail logid"): row for row in details
    }
    missing_csv = 0
    imported_details = telemetry_rows = 0
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
        status = _integer(row.get("status"), "delivery status")
        detail_row = detail_by_id.get(logid)
        if detail_row is None:
            stored_detail = placeholder_detail(delivered=status == 1, ats=_integer(row.get("unit"), "delivery unit") == 2)
        else:
            stored_detail = exported_detail(detail_row.get("detail"), logid)
            imported_details += 1
        values = [
            logid, userid, stored_detail, row.get("max_speed"),
            _timestamp(row.get("timestamp"), "delivery timestamp"),
            status, row.get("profit"),
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
            _integer(row.get("cargo_mass"), "delivery cargo mass", optional=True),
            DETAIL_MARKER if detail_row is None else "",
        ]
        statements.append("INSERT INTO `dlog_meta` (`logid`,`source_city`,`source_company`,`destination_city`,`destination_company`,`cargo_name`,`cargo_mass`,`note`) VALUES (" + ",".join(_sql_value(value) for value in meta) + ");")
        if detail_row is not None:
            telemetry = detail_row.get("telemetry")
            if isinstance(telemetry, str) and telemetry:
                stored_telemetry = telemetry[2:] if telemetry[:2] in {"v1", "v2", "v3", "v4", "v5"} else telemetry
                statements.append(
                    "INSERT INTO `telemetry` (`logid`,`uuid`,`userid`,`data`) VALUES ("
                    + ",".join(_sql_value(value) for value in [logid, "", userid, _compressed_text(stored_telemetry)])
                    + ");"
                )
                telemetry_rows += 1
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready", "deliveries": len(deliveries),
        "detail_placeholders": len(deliveries) - imported_details,
        "imported_details": imported_details, "imported_telemetry": telemetry_rows,
        "missing_csv_metadata": missing_csv,
        "duplicate_csv_rows_ignored": duplicate_csv_rows,
        "csv_only_rows_not_imported": csv_only, "detail_marker": DETAIL_MARKER,
        "database_time_zone": "+00:00",
    }
