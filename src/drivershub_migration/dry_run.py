"""Create a non-writing destination import dry run."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Callable

from .storage import write_json
from .target import preflight_target


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
    baseline_deliveries = _items(csv_entry)
    detail_deliveries = _items(detail_entry)
    missing_details = max(baseline_deliveries - detail_deliveries, 0)

    report = {
        "format_version": 1,
        "state": "ready" if plan_ready and bootstrap_ready else "blocked",
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
            "deliveries": {
                "state": "ready" if csv_entry.get("state") == "complete" else "blocked",
                "baseline_items": baseline_deliveries,
                "list_items": _items(list_entry),
                "detail_items": detail_deliveries,
                "placeholder_items": missing_details,
                "detail_strategy": (
                    "import-exported-details"
                    if missing_details == 0
                    else "schema-placeholders-with-optional-backfill"
                ),
            },
        },
        "writes": 0,
        "target_modified": False,
    }
    write_json(migration_directory / "import-dry-run.json", report)
    return report
