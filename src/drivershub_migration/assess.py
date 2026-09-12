"""Read-only assessment of a source Drivers Hub."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from .http import HttpClient, RequestFailed
from .storage import WorkJournal, atomic_write, sha256, write_json


ENDPOINTS = (
    ("index", "", False),
    ("status", "status", False),
    ("backend-config", "config", True),
    ("client-config", "client/config/global", False),
)


def normalize_api_url(value: str) -> str:
    if not value.startswith(("http://", "https://")):
        raise ValueError("The API URL must start with http:// or https://")
    return value.rstrip("/") + "/"


def derive_capabilities(results: dict[str, object]) -> dict[str, object]:
    backend = results.get("backend-config")
    administrative_config = isinstance(backend, dict) and {
        "config",
        "backup",
        "config_last_modified",
        "backup_last_modified",
    }.issubset(backend)
    client = results.get("client-config")
    client_config = isinstance(client, dict) and "error" not in client
    plugins = client.get("plugins", []) if client_config else []
    detected_external = ["client-config"] if client_config else []
    return {
        "administrative_config": administrative_config,
        "standard_plugins": plugins if isinstance(plugins, list) else [],
        "external_plugins": {
            "state": "partial",
            "detected": detected_external,
            "reason": "The source API does not expose the complete external plugin list.",
        },
        "client_config": client_config,
    }


def assess(
    source: str,
    output: Path,
    token: str | None,
    *,
    request_interval: float = 0.6,
) -> dict[str, object]:
    source = normalize_api_url(source)
    authorization = f"Application {token}" if token else None
    client = HttpClient(authorization, minimum_interval=request_interval)
    journal = WorkJournal(output)
    raw_directory = output / "raw" / "assessment"
    results: dict[str, object] = {}

    for name, relative_url, authenticated in ENDPOINTS:
        key = f"assessment/{name}"
        raw_path = raw_directory / f"{name}.json"
        if journal.completed(key) and raw_path.exists():
            results[name] = json.loads(raw_path.read_bytes())
            continue
        if authenticated and not token:
            journal.record(key, {"state": "skipped", "reason": "application token not supplied"})
            results[name] = {"state": "skipped", "reason": "application token not supplied"}
            continue
        url = urljoin(source, relative_url)
        try:
            response = client.get(url)
        except RequestFailed as exc:
            status = exc.response.status if exc.response else None
            journal.record(key, {"state": "failed", "url": url, "status": status, "error": str(exc)})
            results[name] = {"state": "failed", "status": status, "error": str(exc)}
            continue
        atomic_write(raw_path, response.body)
        journal.record(
            key,
            {
                "state": "complete",
                "url": url,
                "status": response.status,
                "content_type": response.content_type,
                "path": str(raw_path.relative_to(output)),
                "sha256": sha256(response.body),
            },
        )
        results[name] = response.json()

    report = {
        "format_version": 1,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "authentication": "application" if token else "none",
        "capabilities": derive_capabilities(results),
        "results": results,
    }
    write_json(output / "assessment.json", report)
    return report
