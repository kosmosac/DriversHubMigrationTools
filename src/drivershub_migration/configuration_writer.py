"""Import backend configuration, frontend configuration, and branding."""

from __future__ import annotations

from base64 import b64encode
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse

from .account_import import _sql_value
from .account_writer import _check_aio_writers, _execute_aio, _execute_mariadb
from .configuration_plan import create_configuration_plan
from .storage import atomic_write, write_json


def _read_object(path: Path, description: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"The {description} is not an object")
    return value


def _merge_backend(source: dict[str, object], target: dict[str, object]) -> dict[str, object]:
    merged = dict(target)
    for key, value in source.items():
        merged[key] = value
    for key, fields in {
        "roles": ("discord_role_id",),
        "application_types": ("discord_role_change", "channel_id", "webhook_url"),
        "divisions": ("channel_id", "webhook_url"),
    }.items():
        source_items = merged.get(key)
        target_items = target.get(key)
        if not isinstance(source_items, list) or not isinstance(target_items, list):
            continue
        target_by_id = {
            item.get("id"): item for item in target_items if isinstance(item, dict)
        }
        for item in source_items:
            if not isinstance(item, dict):
                continue
            existing = target_by_id.get(item.get("id"))
            if isinstance(existing, dict):
                for field in fields:
                    if field in existing:
                        item[field] = existing[field]

    source_rank_types = merged.get("rank_types")
    target_rank_types = target.get("rank_types")
    if isinstance(source_rank_types, list) and isinstance(target_rank_types, list):
        target_types = {
            item.get("id"): item for item in target_rank_types if isinstance(item, dict)
        }
        for rank_type in source_rank_types:
            if not isinstance(rank_type, dict):
                continue
            existing_type = target_types.get(rank_type.get("id"))
            details = rank_type.get("details")
            existing_details = existing_type.get("details") if isinstance(existing_type, dict) else None
            if not isinstance(details, list) or not isinstance(existing_details, list):
                continue
            existing_by_points = {
                item.get("points"): item
                for item in existing_details
                if isinstance(item, dict)
            }
            for rank in details:
                if not isinstance(rank, dict):
                    continue
                existing = existing_by_points.get(rank.get("points"))
                if isinstance(existing, dict) and "discord_role_id" in existing:
                    rank["discord_role_id"] = existing["discord_role_id"]
    return merged


def _client_config(
    plan: dict[str, object], backend: dict[str, object]
) -> dict[str, object]:
    frontend = plan.get("frontend", {})
    portable = frontend.get("portable", {}) if isinstance(frontend, dict) else {}
    result = dict(portable) if isinstance(portable, dict) else {}
    domain_value = str(backend.get("domain", ""))
    api_host = domain_value if "://" in domain_value else "https://" + domain_value
    parsed = urlparse(api_host)
    host = parsed.netloc or parsed.path
    result.update(
        {
            "abbr": backend.get("abbr", ""),
            "domain": host,
            "api_host": api_host,
            "plugins": backend.get("plugins", []),
        }
    )
    branding = plan.get("branding", {})
    for name in ("logo", "banner", "bgimage"):
        entry = branding.get(name, {}) if isinstance(branding, dict) else {}
        result[f"{name}_key"] = (
            str(entry.get("sha256", ""))[:8]
            if isinstance(entry, dict) and entry.get("state") == "ready"
            else ""
        )
    return result


def _compressed_asset(raw: bytes) -> str:
    try:
        import zstandard
    except ImportError as exc:
        raise ValueError("Install project dependencies to import branding assets") from exc
    encoded = b64encode(raw)
    return b64encode(zstandard.ZstdCompressor().compress(encoded)).decode()


def _database_sql(
    directory: Path, plan: dict[str, object], backend: dict[str, object]
) -> tuple[str, int]:
    client = json.dumps(_client_config(plan, backend), separators=(",", ":"))
    statements = [
        "SET time_zone = '+00:00';",
        "START TRANSACTION;",
        "DELETE FROM `settings` WHERE `skey`='client-config/meta';",
        "INSERT INTO `settings` (`uid`,`skey`,`sval`) VALUES "
        f"(NULL,'client-config/meta',{_sql_value(client)});",
    ]
    assets = 0
    branding = plan.get("branding", {})
    for name in ("logo", "banner", "bgimage"):
        entry = branding.get(name, {}) if isinstance(branding, dict) else {}
        if not isinstance(entry, dict) or entry.get("state") != "ready":
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            raise ValueError(f"The {name} asset has no path")
        try:
            value = _compressed_asset((directory / path).read_bytes())
        except OSError as exc:
            raise ValueError(f"Unable to read the {name} asset") from exc
        statements.extend(
            [
                f"DELETE FROM `ext_assets` WHERE `akey`='client-config/{name}';",
                "INSERT INTO `ext_assets` (`akey`,`aval`) VALUES "
                f"('client-config/{name}',{_sql_value(value)});",
            ]
        )
        assets += 1
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", assets


def import_configuration(
    directory: Path,
    target_directory: Path | None,
    config_path: Path | None,
    *,
    mode: str,
    database: dict[str, object],
    approved: bool,
    backup_confirmed: bool,
    writers_stopped: bool,
    runner=subprocess.run,
) -> dict[str, object]:
    if not approved or not backup_confirmed:
        raise ValueError("The configuration import requires --approve and --backup-confirmed")
    journal_path = directory / "import-journal.json"
    journal = _read_object(journal_path, "import journal")
    if journal.get("stages", {}).get("accounts", {}).get("state") != "complete":
        raise ValueError("Import accounts before configuration")
    if journal.get("stages", {}).get("configuration", {}).get("state") == "complete":
        raise ValueError("The configuration import is already complete")
    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        target = target_directory.resolve()
        _check_aio_writers(target, runner)
        destination_config = target / "config" / "config.json"
    elif mode == "mariadb":
        if not writers_stopped:
            raise ValueError("Direct MariaDB mode requires --writers-stopped")
        if config_path is None:
            raise ValueError("Direct MariaDB mode requires DRIVERSHUB_TARGET_CONFIG_PATH")
        target = None
        destination_config = config_path.resolve()
    else:
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")

    target_config = _read_object(destination_config, "destination backend configuration")
    plan = create_configuration_plan(directory)
    backend_plan = plan.get("backend", {})
    portable = backend_plan.get("portable", {}) if isinstance(backend_plan, dict) else {}
    if not isinstance(portable, dict):
        raise ValueError("The portable backend configuration is invalid")
    merged = _merge_backend(portable, target_config)
    sql, asset_count = _database_sql(directory, plan, merged)
    original = destination_config.read_bytes()
    try:
        atomic_write(
            destination_config,
            (json.dumps(merged, indent=4, ensure_ascii=False) + "\n").encode(),
        )
        if mode == "aio":
            _execute_aio(target, sql, runner)
        else:
            _execute_mariadb(sql, database)
    except Exception:
        atomic_write(destination_config, original)
        raise

    stage = {
        "state": "complete",
        "portable_backend_values": len(portable),
        "branding_assets": asset_count,
        "database_time_zone": "+00:00",
        "protected_destination_values_retained": sorted(
            backend_plan.get("protected", {})
            if isinstance(backend_plan, dict)
            else {}
        ),
    }
    journal.setdefault("stages", {})["configuration"] = stage
    write_json(journal_path, journal)
    return stage
