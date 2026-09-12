"""Initial read-only source export."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from .assess import assess, normalize_api_url
from .http import HttpClient, RequestFailed
from .pagination import export_paginated
from .storage import WorkJournal, atomic_write, sha256, write_json


ASSETS = ("logo", "banner", "bgimage")
PAGINATED_RESOURCES = (
    ("users", "user/list", {"order_by": "uid", "order": "asc"}),
    ("members", "member/list", {"order_by": "userid", "order": "asc"}),
    ("bans", "user/ban/list", {"order_by": "uid", "order": "asc"}),
)


def export_source(source: str, output: Path, token: str) -> dict[str, object]:
    source = normalize_api_url(source)
    assessment = assess(source, output, token)
    capabilities = assessment["capabilities"]
    if not capabilities["administrative_config"]:
        raise RuntimeError(
            "The application token did not provide the administrative configuration"
        )

    journal = WorkJournal(output)
    client = HttpClient(f"Application {token}")
    assets: dict[str, object] = {}
    asset_directory = output / "raw" / "branding"

    if not capabilities["client_config"]:
        assets = {name: {"state": "unavailable"} for name in ASSETS}
    else:
        for name in ASSETS:
            key = f"branding/{name}"
            path = asset_directory / f"{name}.png"
            if journal.completed(key) and path.exists():
                assets[name] = journal.entry(key)
                continue
            url = urljoin(source, f"client/assets/{name}")
            try:
                response = client.get(url, expect_json=False)
            except RequestFailed as exc:
                status = exc.response.status if exc.response else None
                state = "unavailable" if status == 404 else "failed"
                value = {"state": state, "url": url, "status": status, "error": str(exc)}
                journal.record(key, value)
                assets[name] = value
                continue
            atomic_write(path, response.body)
            value = {
                "state": "complete",
                "url": url,
                "status": response.status,
                "content_type": response.content_type,
                "path": str(path.relative_to(output)),
                "sha256": sha256(response.body),
            }
            journal.record(key, value)
            assets[name] = value

    resources: dict[str, object] = {}
    for name, relative_url, query in PAGINATED_RESOURCES:
        resources[name] = export_paginated(
            name=name,
            source=source,
            relative_url=relative_url,
            output=output,
            client=client,
            journal=journal,
            query=query,
        )

    report = {
        "format_version": 1,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": [
            "backend_configuration",
            "frontend_configuration",
            "branding",
            "users",
            "members",
            "bans",
        ],
        "capabilities": capabilities,
        "assets": assets,
        "resources": resources,
    }
    write_json(output / "export.json", report)
    return report
