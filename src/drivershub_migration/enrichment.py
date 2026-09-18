"""Resumable post-migration enrichment jobs safe for a running destination."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Callable
from urllib.parse import urlencode

from .account_import import _sql_value
from .delivery_import import DETAIL_MARKER, exported_detail, placeholder_detail, _compressed_text
from .http import HttpClient, RequestFailed
from .live_target import execute_live, query_rows
from .storage import WorkJournal, atomic_write, sha256, write_json


ECONOMY_MARKER = "migration-import/pending-enrichment"
ECONOMY_ENRICHED_MARKER = "migration-import/internal-note-unavailable"
ECONOMY_UNAVAILABLE_MARKER = "migration-import/enrichment-unavailable"
DELIVERY_UNAVAILABLE_MARKER = "migration-import/detail-unavailable"


def _duration(seconds: float) -> str:
    value = max(0, int(seconds))
    hours, value = divmod(value, 3600)
    minutes, seconds = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class _Progress:
    def __init__(self, total: int, callback: Callable[[str], None] | None, initial_seconds: float) -> None:
        self.total = total
        self.callback = callback
        self.initial_seconds = initial_seconds
        self.started = time.monotonic()
        self.processed = 0
        # Gather roughly 30 seconds of observations, but do not make slow
        # endpoints wait through dozens of rate-limited requests.
        self.sample_target = max(3, min(25, math.ceil(30 / initial_seconds)))

    def show(self) -> None:
        if not self.callback:
            return
        elapsed = time.monotonic() - self.started
        observed = elapsed / self.processed if self.processed else 0.0
        if self.processed < self.sample_target:
            seconds_per_item = max(self.initial_seconds, observed)
            eta_label = "provisional ETA"
        else:
            # Retries and source load can vary during a long run. Keep a
            # modest reserve instead of presenting the current mean as exact.
            # The first request is not rate-limit delayed, so a small sample
            # must never project a cycle below the known steady-state floor.
            seconds_per_item = max(self.initial_seconds, observed * 1.1)
            eta_label = "ETA"
        eta = seconds_per_item * max(0, self.total - self.processed)
        percent = 100.0 if self.total == 0 else self.processed * 100.0 / self.total
        self.callback(
            f"Progress {self.processed}/{self.total} ({percent:.1f}%); "
            f"elapsed {_duration(elapsed)}; {eta_label} {_duration(eta)}"
        )

    def advance(self) -> None:
        self.processed += 1
        self.show()

    def discard(self, count: int) -> None:
        """Remove requests that became unnecessary while a run is active."""
        self.total = max(self.processed, self.total - max(0, count))
        self.show()


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
    mode: str, database: dict[str, object],
    request_interval: float, limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    _import_complete(directory, "deliveries")
    rows = query_rows(
        "SELECT d.logid,d.isdelivered,d.unit FROM dlog d JOIN dlog_meta m ON m.logid=d.logid "
        f"WHERE m.note={_sql_value(DETAIL_MARKER)} ORDER BY d.logid;",
        target_directory, mode=mode, database=database, runner=runner,
    )
    journal = WorkJournal(directory / "enrichment" / "deliveries")
    client = HttpClient(
        f"Application {token}",
        minimum_interval=request_interval,
        progress=progress,
    )
    if progress:
        suffix = f" (limited to {limit} requests)" if limit is not None else ""
        progress(f"Delivery backfill found {len(rows)} marked placeholders{suffix}")
    progress_state = _Progress(
        min(len(rows), limit) if limit is not None else len(rows),
        progress,
        max(request_interval + 0.75, request_interval * 1.1, 0.1),
    )
    progress_state.show()
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
            if state == "unavailable":
                expected = placeholder_detail(delivered=delivered == 1, ats=unit == 2)
                execute_live(
                    "UPDATE dlog d JOIN dlog_meta m ON m.logid=d.logid "
                    f"SET m.note={_sql_value(DELIVERY_UNAVAILABLE_MARKER)} "
                    f"WHERE d.logid={logid} AND m.note={_sql_value(DETAIL_MARKER)} "
                    f"AND d.data={_sql_value(expected)};\n",
                    target_directory, mode=mode, database=database, runner=runner,
                )
            journal.record(key, {
                "state": state, "logid": logid, "attempts": attempts,
                "url": url, "status": response.status if response else None,
                "error": str(exc),
            })
            unavailable += state == "unavailable"
            failed += state == "failed"
            if response is not None and response.status in {401, 403}:
                raise ValueError(
                    f"The source rejected the application token with HTTP {response.status}"
                ) from exc
        progress_state.advance()
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


def _economy_partition_txids(directory: Path) -> dict[int, set[int]]:
    """Map each raw transaction-list partition to the IDs it contained."""
    raw = directory / "raw" / "economy-transactions"
    found: dict[int, set[int]] = {}
    if not raw.is_dir():
        return found
    for partition in raw.glob("userid-*"):
        try:
            userid = int(partition.name.removeprefix("userid-"))
        except ValueError:
            continue
        txids: set[int] = set()
        for page_path in partition.glob("page-*.json"):
            try:
                page = json.loads(page_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(page, dict) or not isinstance(page.get("list"), list):
                continue
            for row in page["list"]:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("txid"), int)
                    and not isinstance(row.get("txid"), bool)
                ):
                    txids.add(row["txid"])
        if txids:
            found[userid] = txids
    return found


def _economy_source_userids(directory: Path, fallback: set[int]) -> set[int]:
    """Return users whose exported transaction history was not empty."""
    raw = directory / "raw" / "economy-transactions"
    if raw.is_dir():
        # An existing raw export is authoritative, including an empty result.
        return set(_economy_partition_txids(directory))
    return fallback


def _economy_user_starts(directory: Path) -> dict[int, int]:
    """Map economy user IDs to the earliest time they can have transactions."""
    path = directory / "normalized" / "profiles.json"
    if not path.exists():
        return {}
    try:
        records = json.loads(path.read_text(encoding="utf-8")).get("records", [])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    starts: dict[int, int] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        userid = row.get("userid")
        joined = row.get("join_timestamp")
        if (
            isinstance(userid, int) and not isinstance(userid, bool)
            and isinstance(joined, int) and not isinstance(joined, bool)
            and joined > 0
        ):
            starts[userid] = max(0, joined - 86400)
    return starts


def _source_offsets(directory: Path) -> dict[str, int]:
    """Derive source-local UTC offsets from two representations of deliveries."""
    deliveries = json.loads(
        (directory / "normalized" / "deliveries.json").read_text(encoding="utf-8")
    ).get("records", [])
    csv_deliveries = json.loads(
        (directory / "normalized" / "deliveries-csv.json").read_text(encoding="utf-8")
    ).get("records", [])
    unix_by_logid = {
        int(row["logid"]): row["timestamp"]
        for row in deliveries
        if isinstance(row, dict)
        and isinstance(row.get("logid"), int)
        and isinstance(row.get("timestamp"), int)
    }
    candidates: dict[str, set[int]] = {}
    for row in csv_deliveries:
        if not isinstance(row, dict):
            continue
        try:
            logid = int(row["logid"])
            local = datetime.strptime(row[" time_submitted"], "%Y-%m-%d %H:%M:%S")
            timestamp = unix_by_logid[logid]
        except (KeyError, TypeError, ValueError):
            continue
        local_as_utc = int(local.replace(tzinfo=timezone.utc).timestamp())
        offset = local_as_utc - timestamp
        # Real civil offsets stay within this range and use 15-minute units.
        if -14 * 3600 <= offset <= 14 * 3600 and offset % 900 == 0:
            candidates.setdefault(local.date().isoformat(), set()).add(offset)
    return {
        date: next(iter(offsets))
        for date, offsets in candidates.items()
        if len(offsets) == 1
    }


def _csv_timestamp(value: str, offsets: dict[str, int]) -> int | None:
    local = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    offset = offsets.get(local.date().isoformat())
    if offset is None:
        return None
    return int(local.replace(tzinfo=timezone.utc).timestamp()) - offset


def enrich_economy_transactions(
    directory: Path, target_directory: Path | None, *, source: str, token: str,
    mode: str, database: dict[str, object],
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    _import_complete(directory, "economy")
    offsets = _source_offsets(directory)
    if not offsets:
        raise ValueError("Unable to derive source time offsets from the delivery exports")
    initial_pending = int(query_rows(
        f"SELECT COUNT(*) FROM economy_transaction WHERE note={_sql_value(ECONOMY_MARKER)};",
        target_directory, mode=mode, database=database, runner=runner,
    )[0][0])
    if initial_pending == 0:
        report = {
            "state": "complete", "attempted_windows": 0,
            "completed_windows": 0, "completed_windows_total": 0,
            "total_windows": 0, "failed_windows": 0,
            "source_rows_processed": 0, "timestamp_candidates": 0,
            "transactions_enriched": 0, "ambiguous_local_timestamps": 0,
            "remaining_transactions": 0, "unavailable_transactions": 0,
        }
        write_json(directory / "enrichment" / "economy-enrichment.json", report)
        return report
    pending_txids = {
        int(row[0]) for row in query_rows(
            f"SELECT txid FROM economy_transaction WHERE note={_sql_value(ECONOMY_MARKER)};",
            target_directory, mode=mode, database=database, runner=runner,
        )
        if row
    }
    balance_data = json.loads((directory / "normalized" / "economy-balances.json").read_text(encoding="utf-8"))
    balance_userids = {
        int(row["userid"])
        for row in balance_data.get("records", [])
        if isinstance(row, dict)
        and isinstance(row.get("userid"), int)
        and not isinstance(row.get("userid"), bool)
    }
    partition_txids = _economy_partition_txids(directory)
    source_userids = _economy_source_userids(directory, balance_userids)
    userids = sorted(
        userid for userid in source_userids
        if not partition_txids or partition_txids.get(userid, set()) & pending_txids
    )
    user_starts = _economy_user_starts(directory)
    start, end = _source_bounds(directory)
    windows = []
    span = 90 * 86400
    for userid in userids:
        cursor = max(start, user_starts.get(userid, start))
        while cursor <= end:
            before = min(end, cursor + span - 1)
            windows.append((userid, cursor, before))
            cursor = before + 1
    journal = WorkJournal(directory / "enrichment" / "economy")
    client = HttpClient(
        f"Application {token}", minimum_interval=20.5, progress=progress
    )
    pending_windows = [
        window for window in windows
        if not journal.completed(f"economy/{window[0]}/{window[1]}-{window[2]}")
    ]
    planned = min(len(pending_windows), limit) if limit is not None else len(pending_windows)
    if progress:
        progress(
            f"Economy enrichment has {len(pending_windows)} remaining source windows; this run will process at most {planned}"
        )
        progress(
            f"Source plan uses {len(userids)} of {len(balance_userids)} economy accounts with exported transactions"
        )
        progress(f"Transactions awaiting enrichment: {initial_pending}")
    progress_state = _Progress(planned, progress, 21.25)
    progress_state.show()
    attempted = completed_windows = failed = source_rows = candidates = enriched = ambiguous = 0
    current_pending = initial_pending
    discarded_keys: set[str] = set()
    exhausted_users: set[int] = set()
    for userid, after, before in windows:
        if limit is not None and attempted >= limit:
            break
        key = f"economy/{userid}/{after}-{before}"
        if journal.completed(key):
            continue
        if userid in exhausted_users:
            continue
        if partition_txids and not (partition_txids.get(userid, set()) & pending_txids):
            exhausted_users.add(userid)
            user_keys = {
                f"economy/{candidate_userid}/{candidate_after}-{candidate_before}"
                for candidate_userid, candidate_after, candidate_before in windows
                if candidate_userid == userid
                and not journal.completed(
                    f"economy/{candidate_userid}/{candidate_after}-{candidate_before}"
                )
            }
            discarded_keys.update(user_keys)
            if limit is None:
                remaining_capacity = max(0, progress_state.total - progress_state.processed)
                progress_state.discard(min(len(user_keys), remaining_capacity))
            if progress:
                progress(
                    f"Skipped {len(user_keys)} remaining windows for account {userid}; "
                    "all of its exported transactions are already enriched"
                )
            continue
        attempted += 1
        old = journal.entry(key) or {}
        attempts = int(old.get("attempts", 0)) + 1
        query = urlencode({"after": after, "before": before})
        url = _base(source) + f"economy/balance/{userid}/transactions/export?{query}"
        journal.record(key, {"state": "in_progress", "userid": userid, "after": after, "before": before, "attempts": attempts, "url": url})
        window_rows = window_candidates = 0
        try:
            response = client.get(url, expect_json=False)
            rows = list(csv.DictReader(StringIO(response.body.decode("utf-8-sig")), skipinitialspace=True))
            updates: list[str] = []
            seen: set[int] = set()
            update_txids: set[int] = set()
            for row in rows:
                txid = int(row["txid"])
                if txid in seen:
                    continue
                seen.add(txid)
                timestamp = _csv_timestamp(row["time"], offsets)
                if timestamp is None:
                    ambiguous += 1
                    continue
                update_txids.add(txid)
                updates.append(
                    "UPDATE economy_transaction SET timestamp=" + str(timestamp)
                    + f",note={_sql_value(ECONOMY_ENRICHED_MARKER)} WHERE txid={txid} AND note={_sql_value(ECONOMY_MARKER)};"
                )
            window_rows = len(seen)
            window_candidates = len(updates)
            pending_txids.difference_update(update_txids)
            # Keep locks short while the destination Hub is serving requests.
            for offset in range(0, len(updates), 250):
                statements = ["SET time_zone='+00:00';", "START TRANSACTION;", *updates[offset:offset + 250], "COMMIT;"]
                execute_live("\n".join(statements) + "\n", target_directory, mode=mode, database=database, runner=runner)
            raw_path = directory / "enrichment" / "economy" / "raw" / f"userid-{userid}-{after}-{before}.csv"
            atomic_write(raw_path, response.body)
            journal.record(key, {"state": "complete", "userid": userid, "after": after, "before": before, "attempts": attempts, "url": url, "rows": len(seen), "source_sha256": sha256(response.body), "completed_at": datetime.now(timezone.utc).isoformat()})
            completed_windows += 1
            source_rows += window_rows
            candidates += window_candidates
        except (RequestFailed, ValueError, KeyError, UnicodeDecodeError) as exc:
            response = exc.response if isinstance(exc, RequestFailed) else None
            journal.record(key, {
                "state": "failed", "userid": userid, "after": after,
                "before": before, "attempts": attempts, "url": url,
                "status": response.status if response else None,
                "error": str(exc),
            })
            failed += 1
            if response is not None and response.status in {401, 403}:
                raise ValueError(
                    f"The source rejected the application token with HTTP {response.status}"
                ) from exc
        previous_pending = current_pending
        current_pending = int(query_rows(
            f"SELECT COUNT(*) FROM economy_transaction WHERE note={_sql_value(ECONOMY_MARKER)};",
            target_directory, mode=mode, database=database, runner=runner,
        )[0][0])
        window_enriched = max(0, previous_pending - current_pending)
        enriched += window_enriched
        progress_state.advance()
        if progress:
            progress(
                f"Window result: {window_rows} source transactions, "
                f"{window_candidates} timestamp candidates, "
                f"{window_enriched} destination transactions enriched"
            )
            progress(f"Transactions awaiting enrichment: {current_pending}")
    remaining = current_pending
    completed_total = sum(
        journal.completed(f"economy/{userid}/{after}-{before}")
        for userid, after, before in windows
    )
    if remaining == 0:
        state = "complete"
    elif completed_total + len(discarded_keys) == len(windows):
        state = "complete-with-gaps"
        left_to_mark = remaining
        while left_to_mark:
            execute_live(
                "UPDATE economy_transaction "
                f"SET note={_sql_value(ECONOMY_UNAVAILABLE_MARKER)} "
                f"WHERE note={_sql_value(ECONOMY_MARKER)} ORDER BY txid LIMIT 500;\n",
                target_directory, mode=mode, database=database, runner=runner,
            )
            left_to_mark = int(query_rows(
                f"SELECT COUNT(*) FROM economy_transaction WHERE note={_sql_value(ECONOMY_MARKER)};",
                target_directory, mode=mode, database=database, runner=runner,
            )[0][0])
    else:
        state = "incomplete"
    unavailable = remaining if state == "complete-with-gaps" else 0
    pending = 0 if state == "complete-with-gaps" else remaining
    report = {
        "state": state,
        "attempted_windows": attempted,
        "completed_windows": completed_windows,
        "completed_windows_total": completed_total,
        "total_windows": len(windows),
        "source_accounts": len(userids),
        "economy_accounts": len(balance_userids),
        "dynamically_skipped_windows": len(discarded_keys),
        "failed_windows": failed,
        "source_rows_processed": source_rows,
        "timestamp_candidates": candidates,
        "transactions_enriched": enriched,
        "ambiguous_local_timestamps": ambiguous,
        "remaining_transactions": pending,
        "unavailable_transactions": unavailable,
    }
    write_json(directory / "enrichment" / "economy-enrichment.json", report)
    return report
