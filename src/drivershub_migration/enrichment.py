"""Resumable post-migration enrichment jobs safe for a running destination."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import subprocess
from typing import Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .account_import import _sql_value
from .delivery_import import DETAIL_MARKER, exported_detail, placeholder_detail, _compressed_text
from .http import HttpClient, RequestFailed
from .live_target import execute_live, query_rows
from .storage import WorkJournal, atomic_write, sha256, write_json


ECONOMY_MARKER = "migration-import/pending-enrichment"
ECONOMY_ENRICHED_MARKER = "migration-import/csv-enriched"


def _import_complete(directory: Path, stage: str) -> None:
    try:
        journal = json.loads((directory / "import-journal.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read the import journal") from exc
    if journal.get("stages", {}).get(stage, {}).get("state") != "complete":
        raise ValueError(f"Complete the {stage} import before running this job")


def _base(source: str) -> str:
    return source.rstrip("/") + "/"


def backfill_delivery_details(
    directory: Path, target_directory: Path | None, *, source: str, token: str,
    mode: str, database: dict[str, object], approved: bool, allow_view_updates: bool,
    request_interval: float, limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    if not approved or not allow_view_updates:
        raise ValueError("Delivery backfill requires --approve and DRIVERSHUB_ALLOW_DELIVERY_VIEW_UPDATES=true")
    _import_complete(directory, "deliveries")
    rows = query_rows(
        "SELECT d.logid,d.isdelivered,d.unit FROM dlog d JOIN dlog_meta m ON m.logid=d.logid "
        f"WHERE m.note={_sql_value(DETAIL_MARKER)} ORDER BY d.logid;",
        target_directory, mode=mode, database=database, runner=runner,
    )
    journal = WorkJournal(directory / "enrichment" / "deliveries")
    client = HttpClient(token, minimum_interval=request_interval, progress=progress)
    if progress:
        suffix = f" (limited to {limit} requests)" if limit is not None else ""
        progress(f"Delivery backfill found {len(rows)} marked placeholders{suffix}")
    completed = failed = unavailable = skipped = attempted = 0
    for fields in rows:
        if limit is not None and attempted >= limit:
            break
        logid, delivered, unit = map(int, fields)
        key = f"delivery/{logid}"
        if journal.completed(key):
            skipped += 1
            continue
        attempted += 1
        entry = journal.entry(key) or {}
        attempts = int(entry.get("attempts", 0)) + 1
        url = _base(source) + f"dlog/{logid}"
        journal.record(key, {"state": "in_progress", "logid": logid, "attempts": attempts, "url": url})
        try:
            response = client.get(url)
            value = response.json()
            if not isinstance(value, dict) or value.get("logid") != logid:
                raise ValueError("The source detail response does not match the delivery ID")
            detail = exported_detail(value.get("detail"), logid)
            telemetry = value.get("telemetry")
            stored_telemetry = None
            if isinstance(telemetry, str) and telemetry:
                telemetry = telemetry[2:] if telemetry[:2] in {"v1", "v2", "v3", "v4", "v5"} else telemetry
                stored_telemetry = _compressed_text(telemetry)
            expected = placeholder_detail(delivered=delivered == 1, ats=unit == 2)
            statements = ["START TRANSACTION;", "SET @migration_eligible=0;"]
            statements.append(
                "SELECT COUNT(*) INTO @migration_eligible FROM dlog d JOIN dlog_meta m ON m.logid=d.logid "
                f"WHERE d.logid={logid} AND m.note={_sql_value(DETAIL_MARKER)} AND d.data={_sql_value(expected)} FOR UPDATE;"
            )
            statements.append(f"UPDATE dlog SET data={_sql_value(detail)} WHERE logid={logid} AND @migration_eligible=1;")
            statements.append(f"DELETE FROM telemetry WHERE logid={logid} AND @migration_eligible=1;")
            if stored_telemetry is not None:
                userid = query_rows(f"SELECT userid FROM dlog WHERE logid={logid};", target_directory, mode=mode, database=database, runner=runner)[0][0]
                statements.append(
                    "INSERT INTO telemetry (logid,uuid,userid,data) SELECT "
                    f"{logid},'',{int(userid)},{_sql_value(stored_telemetry)} WHERE @migration_eligible=1;"
                )
            statements.append(f"UPDATE dlog_meta SET note='' WHERE logid={logid} AND @migration_eligible=1;")
            statements.append("COMMIT;")
            execute_live("\n".join(statements) + "\n", target_directory, mode=mode, database=database, runner=runner)
            remaining = query_rows(
                f"SELECT COUNT(*) FROM dlog_meta WHERE logid={logid} AND note={_sql_value(DETAIL_MARKER)};",
                target_directory, mode=mode, database=database, runner=runner,
            )[0][0]
            if int(remaining):
                raise ValueError("Destination no longer contains the exact migration placeholder")
            raw_path = directory / "enrichment" / "deliveries" / "raw" / f"logid-{logid}.json"
            atomic_write(raw_path, response.body)
            journal.record(key, {
                "state": "complete", "logid": logid, "attempts": attempts, "url": url,
                "source_sha256": sha256(response.body), "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            completed += 1
        except (RequestFailed, ValueError, IndexError) as exc:
            response = exc.response if isinstance(exc, RequestFailed) else None
            state = "unavailable" if response is not None and response.status == 404 else "failed"
            journal.record(key, {"state": state, "logid": logid, "attempts": attempts, "url": url, "error": str(exc)})
            unavailable += state == "unavailable"
            failed += state == "failed"
    remaining = int(query_rows(
        f"SELECT COUNT(*) FROM dlog_meta WHERE note={_sql_value(DETAIL_MARKER)};",
        target_directory, mode=mode, database=database, runner=runner,
    )[0][0])
    report = {"state": "complete" if remaining == 0 else "incomplete", "attempted": attempted, "completed": completed, "failed": failed, "unavailable": unavailable, "already_completed": skipped, "remaining": remaining}
    write_json(directory / "enrichment" / "delivery-backfill.json", report)
    return report


def _source_bounds(directory: Path) -> tuple[int, int]:
    timestamps: list[int] = []
    for name in ("members", "profiles", "deliveries"):
        path = directory / "normalized" / f"{name}.json"
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        for row in value.get("records", []):
            if not isinstance(row, dict):
                continue
            candidates = [row.get("timestamp"), row.get("join_timestamp")]
            user = row.get("user")
            if isinstance(user, dict):
                candidates.append(user.get("join_timestamp"))
            timestamps.extend(v for v in candidates if isinstance(v, int) and v > 0)
    if not timestamps:
        raise ValueError("Unable to derive the source history start time")
    try:
        export = json.loads((directory / "export.json").read_text(encoding="utf-8"))
        end = int(datetime.fromisoformat(export["created_at"]).timestamp())
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to derive the source export time") from exc
    return max(0, min(timestamps) - 86400), end


def _csv_timestamp(value: str, zone: ZoneInfo) -> int | None:
    """Convert an offset-free local time only when it identifies one instant."""
    naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    candidates = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        timestamp = int(aware.timestamp())
        if datetime.fromtimestamp(timestamp, zone).replace(tzinfo=None) == naive:
            candidates.add(timestamp)
    return next(iter(candidates)) if len(candidates) == 1 else None


def enrich_economy_transactions(
    directory: Path, target_directory: Path | None, *, source: str, token: str,
    source_timezone: str, mode: str, database: dict[str, object], approved: bool,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    if not approved:
        raise ValueError("Economy enrichment requires --approve")
    _import_complete(directory, "economy")
    try:
        zone = ZoneInfo(source_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("DRIVERSHUB_SOURCE_TIMEZONE is not a valid IANA time zone") from exc
    balance_data = json.loads((directory / "normalized" / "economy-balances.json").read_text(encoding="utf-8"))
    userids = sorted({int(row["userid"]) for row in balance_data.get("records", []) if isinstance(row, dict) and isinstance(row.get("userid"), int)})
    start, end = _source_bounds(directory)
    windows = []
    cursor = start
    span = 90 * 86400
    while cursor <= end:
        before = min(end, cursor + span - 1)
        windows.extend((userid, cursor, before) for userid in userids)
        cursor = before + 1
    journal = WorkJournal(directory / "enrichment" / "economy")
    client = HttpClient(token, minimum_interval=20.5, progress=progress)
    if progress:
        planned = min(len(windows), limit) if limit is not None else len(windows)
        progress(
            f"Economy enrichment has {len(windows)} source windows; this run will process at most {planned}"
        )
    attempted = completed_windows = failed = updated = ambiguous = 0
    for userid, after, before in windows:
        if limit is not None and attempted >= limit:
            break
        key = f"economy/{userid}/{after}-{before}"
        if journal.completed(key):
            continue
        attempted += 1
        old = journal.entry(key) or {}
        attempts = int(old.get("attempts", 0)) + 1
        query = urlencode({"after": after, "before": before})
        url = _base(source) + f"economy/balance/{userid}/transactions/export?{query}"
        journal.record(key, {"state": "in_progress", "userid": userid, "after": after, "before": before, "attempts": attempts, "url": url})
        try:
            response = client.get(url, expect_json=False)
            rows = list(csv.DictReader(StringIO(response.body.decode("utf-8-sig")), skipinitialspace=True))
            updates: list[str] = []
            seen: set[int] = set()
            for row in rows:
                txid = int(row["txid"])
                if txid in seen:
                    continue
                seen.add(txid)
                timestamp = _csv_timestamp(row["time"], zone)
                if timestamp is None:
                    ambiguous += 1
                    continue
                updates.append(
                    "UPDATE economy_transaction SET timestamp=" + str(timestamp)
                    + f",note={_sql_value(ECONOMY_ENRICHED_MARKER)} WHERE txid={txid} AND note={_sql_value(ECONOMY_MARKER)};"
                )
            # Keep locks short while the destination Hub is serving requests.
            for offset in range(0, len(updates), 250):
                statements = ["SET time_zone='+00:00';", "START TRANSACTION;", *updates[offset:offset + 250], "COMMIT;"]
                execute_live("\n".join(statements) + "\n", target_directory, mode=mode, database=database, runner=runner)
            raw_path = directory / "enrichment" / "economy" / "raw" / f"userid-{userid}-{after}-{before}.csv"
            atomic_write(raw_path, response.body)
            journal.record(key, {"state": "complete", "userid": userid, "after": after, "before": before, "attempts": attempts, "url": url, "rows": len(seen), "source_sha256": sha256(response.body), "completed_at": datetime.now(timezone.utc).isoformat()})
            completed_windows += 1
            updated += len(seen)
        except (RequestFailed, ValueError, KeyError, UnicodeDecodeError) as exc:
            journal.record(key, {"state": "failed", "userid": userid, "after": after, "before": before, "attempts": attempts, "url": url, "error": str(exc)})
            failed += 1
    remaining = int(query_rows(
        f"SELECT COUNT(*) FROM economy_transaction WHERE note={_sql_value(ECONOMY_MARKER)};",
        target_directory, mode=mode, database=database, runner=runner,
    )[0][0])
    completed_total = sum(
        journal.completed(f"economy/{userid}/{after}-{before}")
        for userid, after, before in windows
    )
    if remaining == 0:
        state = "complete"
    elif completed_total == len(windows):
        state = "complete-with-gaps"
    else:
        state = "incomplete"
    report = {
        "state": state,
        "attempted_windows": attempted,
        "completed_windows": completed_windows,
        "completed_windows_total": completed_total,
        "total_windows": len(windows),
        "failed_windows": failed,
        "source_rows_processed": updated,
        "ambiguous_local_timestamps": ambiguous,
        "remaining_transactions": remaining,
    }
    write_json(directory / "enrichment" / "economy-enrichment.json", report)
    return report
