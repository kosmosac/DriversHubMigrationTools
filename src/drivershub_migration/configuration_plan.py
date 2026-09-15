"""Plan portable backend configuration, frontend configuration, and branding."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


DESTINATION_BACKEND_FIELDS = {
    "trackers",
    "captcha",
    "discord_guild_id",
    "discord_client_id",
    "discord_client_secret",
    "discord_bot_token",
    "steam_api_key",
    "smtp_host",
    "smtp_port",
    "smtp_email",
    "smtp_password",
    "smtp_encryption",
    "hook_delivery_log",
    "delivery_webhook_image_urls",
    "discord_guild_message_replace_rules",
    "hook_audit_log",
    "member_accept",
    "member_leave",
    "driver_role_add",
    "driver_role_remove",
    "rank_up",
    "announcement_forwarding",
    "challenge_forwarding",
    "challenge_completed_forwarding",
    "downloads_forwarding",
    "event_forwarding",
    "event_upcoming_forwarding",
}


def _destination_managed(key: str) -> bool:
    return (
        key in DESTINATION_BACKEND_FIELDS
        or key.startswith("db_")
        or key.startswith("redis_")
    )


def _without_destination_links(key: str, value: object) -> object:
    value = deepcopy(value)
    if key == "roles" and isinstance(value, list):
        for role in value:
            if isinstance(role, dict):
                role["discord_role_id"] = None
    elif key == "application_types" and isinstance(value, list):
        for application in value:
            if isinstance(application, dict):
                application["discord_role_change"] = []
                application["channel_id"] = ""
                application["webhook_url"] = ""
    elif key == "divisions" and isinstance(value, list):
        for division in value:
            if isinstance(division, dict):
                division["channel_id"] = ""
                division["webhook_url"] = ""
    elif key == "rank_types" and isinstance(value, list):
        for rank_type in value:
            if not isinstance(rank_type, dict) or not isinstance(rank_type.get("details"), list):
                continue
            for rank in rank_type["details"]:
                if isinstance(rank, dict):
                    rank["discord_role_id"] = None
    return value

RUNTIME_FRONTEND_FIELDS = {
    "abbr",
    "domain",
    "api_host",
    "plugins",
}

BRANDING_KEY_FIELDS = {
    "logo_key",
    "banner_key",
    "bgimage_key",
}


def _read_object(path: Path, description: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"The export does not contain valid {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"The exported {description} is not an object")
    return value


def create_configuration_plan(directory: Path) -> dict[str, object]:
    backend_document = _read_object(
        directory / "raw" / "assessment" / "backend-config.json",
        "backend configuration",
    )
    client_config = _read_object(
        directory / "raw" / "assessment" / "client-config.json",
        "frontend configuration",
    )
    export = _read_object(directory / "export.json", "export manifest")

    backend_config = backend_document.get("config")
    if not isinstance(backend_config, dict):
        raise ValueError("The exported backend configuration has no config object")

    portable_backend: dict[str, object] = {}
    protected: dict[str, dict[str, object]] = {}
    for key, value in backend_config.items():
        if _destination_managed(key):
            protected[key] = {
                "state": "retain-destination-value",
                "reason": "This infrastructure or integration value belongs to the destination.",
            }
        else:
            portable_backend[key] = _without_destination_links(key, value)

    portable_frontend = {
        key: value
        for key, value in client_config.items()
        if key not in RUNTIME_FRONTEND_FIELDS | BRANDING_KEY_FIELDS
    }
    runtime_frontend = {
        key: "derive-from-destination-backend"
        for key in RUNTIME_FRONTEND_FIELDS
        if key in client_config
    }

    assets: dict[str, object] = {}
    manifest_assets = export.get("assets")
    if isinstance(manifest_assets, dict):
        for name in ("logo", "banner", "bgimage"):
            entry = manifest_assets.get(name)
            if not isinstance(entry, dict):
                assets[name] = {"state": "unavailable"}
                continue
            if entry.get("state") == "complete" and isinstance(entry.get("path"), str):
                assets[name] = {
                    "state": "ready",
                    "path": entry["path"],
                    "sha256": entry.get("sha256"),
                }
            else:
                assets[name] = {
                    "state": entry.get("state", "unavailable"),
                    "reason": entry.get("reason") or entry.get("error"),
                }

    return {
        "state": "complete",
        "backend": {
            "portable": portable_backend,
            "protected": protected,
            "merge_policy": "preserve-non-exported-destination-values",
        },
        "frontend": {
            "portable": portable_frontend,
            "runtime_managed": runtime_frontend,
            "branding_keys": {
                key: "derive-from-imported-asset"
                for key in BRANDING_KEY_FIELDS
                if key in client_config
            },
        },
        "branding": assets,
    }
