"""Plan portable backend configuration, frontend configuration, and branding."""

from __future__ import annotations

import json
from pathlib import Path


PROTECTED_BACKEND_FIELDS = {
    "discord_client_secret",
    "discord_bot_token",
    "steam_api_key",
    "smtp_password",
}

RUNTIME_FRONTEND_FIELDS = {
    "abbr",
    "domain",
    "api_host",
    "plugins",
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
        if key in PROTECTED_BACKEND_FIELDS and value in {None, ""}:
            protected[key] = {
                "state": "destination-value-required",
                "reason": "The source API does not return this protected value.",
            }
        else:
            portable_backend[key] = value

    portable_frontend = {
        key: value
        for key, value in client_config.items()
        if key not in RUNTIME_FRONTEND_FIELDS
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
        },
        "branding": assets,
    }
