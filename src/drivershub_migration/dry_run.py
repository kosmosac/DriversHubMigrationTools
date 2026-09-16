"""Create a non-writing destination import dry run."""

from __future__ import annotations

import json
import csv
from pathlib import Path
import subprocess
from typing import Callable

from .storage import write_json
from .target import preflight_target
from .import_validation import validate_import


DELIVERY_TIMESTAMP_SOURCE = "normalized/deliveries.json:timestamp"
MAX_UNIX_SECONDS = 32_503_680_000  # 3000-01-01T00:00:00Z


def _validate_delivery_timestamps(
    migration_directory: Path,
    csv_entry: dict[str, object],
    list_entry: dict[str, object],
) -> tuple[bool, int, int, str | None]:
    relative_path = list_entry.get("path")
    if not isinstance(relative_path, str):
        return False, 0, 0, "The delivery list has no normalized data path."
    try:
        payload = _read_object(
            migration_directory / relative_path, "normalized delivery list"
        )
    except ValueError as exc:
        return False, 0, 0, str(exc)
    records = payload.get("records")
    if not isinstance(records, list):
        return False, 0, 0, "The normalized delivery list has no records array."
    timestamp_ids: set[str] = set()
    for index, record in enumerate(records):
        timestamp = record.get("timestamp") if isinstance(record, dict) else None
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or not 0 <= timestamp <= MAX_UNIX_SECONDS
        ):
            return False, index, 0, (
                f"Delivery record {index} has no valid Unix-seconds timestamp."
            )
        logid = record.get("logid")
        if isinstance(logid, bool) or not isinstance(logid, int):
            return False, index, 0, f"Delivery record {index} has no valid logid."
        timestamp_ids.add(str(logid))

    csv_path = csv_entry.get("path")
    if not isinstance(csv_path, str):
        return False, len(records), 0, "The delivery CSV has no data path."
    try:
        with (migration_directory / csv_path).open(
            newline="", encoding="utf-8"
        ) as handle:
            csv_ids = {
                row.get("logid")
                for row in csv.DictReader(handle)
                if row.get("logid") is not None
            }
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return False, len(records), 0, f"Unable to read delivery CSV: {exc}"
    missing = csv_ids - timestamp_ids
    if missing:
        return False, len(records), len(csv_ids), (
            f"{len(missing)} delivery IDs have no numeric timestamp source."
        )
    return True, len(records), len(csv_ids), None


def _delivery_timestamp_policy(
    migration_directory: Path,
    csv_entry: dict[str, object],
    list_entry: dict[str, object],
) -> dict[str, object]:
    """Describe and enforce the timezone-safe delivery import source."""
    list_ready = list_entry.get("state") == "complete"
    valid, checked, covered, error = (
        _validate_delivery_timestamps(migration_directory, csv_entry, list_entry)
        if list_ready
        else (False, 0, 0, "The normalized delivery list is not complete.")
    )
    return {
        "state": "ready" if valid else "blocked",
        "storage": "unix-seconds",
        "source": DELIVERY_TIMESTAMP_SOURCE,
        "preserve_numeric_value": True,
        "csv_time_submitted": "display-only",
        "naive_datetime_conversion": "forbidden",
        "validated_records": checked,
        "covered_csv_logids": covered,
        "error": error,
        "reason": (
            "The numeric delivery-list timestamp is independent of source and "
            "destination time zones. The CSV time_submitted value is formatted "
            "in the source server's local time without a UTC offset and must not "
            "be used for database imports."
        ),
    }


def _read_object(path: Path, description: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"The {description} is not an object")
    return value


def _items(value: object) -> int:
    return value.get("items", 0) if isinstance(value, dict) and isinstance(value.get("items", 0), int) else 0


def _resource_counts(export: dict[str, object]) -> dict[str, int]:
    resources = export.get("resources", {})
    if not isinstance(resources, dict):
        return {}
    return {
        name: _items(entry)
        for name, entry in resources.items()
        if isinstance(entry, dict)
        and entry.get("state") == "complete"
    }


def _plugin_counts(export: dict[str, object]) -> dict[str, int]:
    plugins = export.get("plugin_resources", {})
    counts: dict[str, int] = {}
    if not isinstance(plugins, dict):
        return counts
    for name, entry in plugins.items():
        if not isinstance(entry, dict) or entry.get("state") not in {
            "complete",
            "configuration-only",
        }:
            continue
        listing = entry.get("list")
        counts[name] = _items(listing) if isinstance(listing, dict) else 0
    return counts


def _economy_counts(export: dict[str, object]) -> dict[str, int]:
    plugins = export.get("plugin_resources", {})
    economy = plugins.get("economy", {}) if isinstance(plugins, dict) else {}
    if not isinstance(economy, dict) or economy.get("state") != "complete":
        return {}
    return {
        name: _items(entry)
        for name, entry in economy.items()
        if isinstance(entry, dict) and entry.get("state") == "complete"
    }


def create_import_dry_run(
    migration_directory: Path,
    target_directory: Path | None = None,
    *,
    mode: str = "aio",
    database: dict[str, object] | None = None,
    config_path: Path | None = None,
    convert_personal_notes: bool = False,
    writers_stopped: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    target = preflight_target(
        migration_directory,
        target_directory,
        mode=mode,
        database=database,
        runner=runner,
    )
    plan = _read_object(migration_directory / "import-plan.json", "import plan")
    export = _read_object(migration_directory / "export.json", "export manifest")

    bootstrap = target.get("bootstrap", {})
    bootstrap_ready = isinstance(bootstrap, dict) and bootstrap.get("state") in {
        "ready",
        "not-required",
    }
    plan_ready = plan.get("state") == "complete"

    configuration = plan.get("configuration", {})
    backend = configuration.get("backend", {}) if isinstance(configuration, dict) else {}
    protected = backend.get("protected", {}) if isinstance(backend, dict) else {}
    branding = configuration.get("branding", {}) if isinstance(configuration, dict) else {}

    deliveries = export.get("deliveries", {})
    csv_entry = deliveries.get("csv", {}) if isinstance(deliveries, dict) else {}
    list_entry = deliveries.get("list", {}) if isinstance(deliveries, dict) else {}
    detail_entry = deliveries.get("details", {}) if isinstance(deliveries, dict) else {}
    csv_entry = csv_entry if isinstance(csv_entry, dict) else {}
    list_entry = list_entry if isinstance(list_entry, dict) else {}
    detail_entry = detail_entry if isinstance(detail_entry, dict) else {}
    baseline_deliveries = _items(list_entry)
    detail_deliveries = _items(detail_entry)
    missing_details = max(baseline_deliveries - detail_deliveries, 0)
    plugins = export.get("plugin_resources", {})
    plugins = plugins if isinstance(plugins, dict) else {}
    poll_entry = plugins.get("poll", {})
    task_entry = plugins.get("task", {})
    economy_entry = plugins.get("economy", {})
    poll_entry = poll_entry if isinstance(poll_entry, dict) else {}
    task_entry = task_entry if isinstance(task_entry, dict) else {}
    economy_entry = economy_entry if isinstance(economy_entry, dict) else {}
    timestamp_policy = _delivery_timestamp_policy(
        migration_directory, csv_entry, list_entry
    )
    deliveries_ready = (
        csv_entry.get("state") == "complete"
        and timestamp_policy["state"] == "ready"
    )

    validation: dict[str, object]
    if plan_ready and bootstrap_ready and deliveries_ready:
        try:
            validation = validate_import(
                migration_directory, target_directory, mode=mode,
                database=database or {}, config_path=config_path,
                convert_personal_notes=convert_personal_notes, runner=runner,
                writers_stopped=writers_stopped,
            )
        except ValueError as exc:
            validation = {"state": "blocked", "error": str(exc), "committed_writes": 0}
    else:
        validation = {
            "state": "blocked",
            "error": "The source plan, destination identity plan, or delivery baseline is not ready.",
            "committed_writes": 0,
        }

    report = {
        "format_version": 1,
        "state": "ready" if validation["state"] == "ready" else "blocked",
        "target_mode": mode,
        "bootstrap": bootstrap,
        "stages": {
            "configuration": {
                "state": "ready" if isinstance(configuration, dict) and configuration.get("state") == "complete" else "blocked",
                "portable_backend_values": len(backend.get("portable", {})) if isinstance(backend, dict) and isinstance(backend.get("portable"), dict) else 0,
                "protected_destination_values": sorted(protected) if isinstance(protected, dict) else [],
                "branding_assets": sum(
                    isinstance(entry, dict) and entry.get("state") == "ready"
                    for entry in branding.values()
                ) if isinstance(branding, dict) else 0,
            },
            "accounts": {
                "state": "ready" if plan_ready else "blocked",
                "items": plan.get("summary", {}).get("accounts", 0) if isinstance(plan.get("summary"), dict) else 0,
                "administrators": plan.get("summary", {}).get("administrators", 0) if isinstance(plan.get("summary"), dict) else 0,
            },
            "core_resources": _resource_counts(export),
            "plugin_resources": _plugin_counts(export),
            "economy": _economy_counts(export),
            "polls_tasks": {
                "polls": _items(poll_entry.get("details")),
                "tasks": _items(task_entry.get("details")),
                "unavailable_vote_timestamps": True,
                "unavailable_task_create_timestamps": True,
            },
            "economy_inventory": {
                "trucks": _items(economy_entry.get("trucks")),
                "garage_slots": _items(economy_entry.get("garage_slots")),
                "merchandise": _items(economy_entry.get("merch")),
                "unavailable_garage_slot_prices": True,
                "unavailable_merchandise_sell_prices": True,
            },
            "deliveries": {
                "state": "ready" if deliveries_ready else "blocked",
                "baseline_items": baseline_deliveries,
                "list_items": _items(list_entry),
                "detail_items": detail_deliveries,
                "placeholder_items": missing_details,
                "detail_strategy": (
                    "import-exported-details"
                    if missing_details == 0
                    else "frontend-placeholders-with-optional-backfill"
                ),
                "timestamp_policy": timestamp_policy,
            },
        },
        "writes": 0,
        "target_modified": False,
        "database_validation": validation,
    }
    write_json(migration_directory / "import-dry-run.json", report)
    return report
