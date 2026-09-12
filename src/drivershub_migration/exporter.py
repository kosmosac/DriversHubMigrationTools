"""Initial read-only source export."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urljoin

from .assess import assess, normalize_api_url
from .http import HttpClient, RequestFailed
from .pagination import export_paginated
from .storage import WorkJournal, atomic_write, sha256, write_json


ASSETS = ("logo", "banner", "bgimage")
PAGINATED_RESOURCES = (
    ("users", "user/list", {"order_by": "uid", "order": "asc"}, None),
    (
        "members",
        "member/list",
        {"order_by": "userid", "order": "asc"},
        "Updates the requesting administrator's activity.",
    ),
    ("bans", "user/ban/list", {"order_by": "uid", "order": "asc"}, None),
)


def _export_profiles(
    source: str,
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
) -> dict[str, object]:
    identities: dict[int, dict[str, object]] = {}
    for resource in ("users", "members"):
        path = output / "normalized" / f"{resource}.json"
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        for record in value.get("records", []):
            if isinstance(record, dict) and isinstance(record.get("uid"), int):
                identities[record["uid"]] = record

    profiles: list[object] = []
    failures: list[dict[str, object]] = []
    raw_directory = output / "raw" / "profiles"
    for uid in sorted(identities):
        key = f"profiles/uid/{uid}"
        path = raw_directory / f"uid-{uid}.json"
        profile = None
        if journal.completed(key) and path.exists():
            try:
                profile = json.loads(path.read_bytes())
            except (json.JSONDecodeError, UnicodeDecodeError):
                profile = None
        url = urljoin(
            source,
            "user/profile",
        ) + f"?uid={uid}&role_history_limit=1000000&ban_history_limit=1000000"
        if profile is None:
            try:
                response = client.get(url)
                profile = response.json()
                if not isinstance(profile, dict) or profile.get("uid") != uid:
                    raise ValueError("The profile response does not match the requested UID")
            except (RequestFailed, ValueError) as exc:
                response = exc.response if isinstance(exc, RequestFailed) else None
                failure = {
                    "state": "failed",
                    "uid": uid,
                    "url": url,
                    "status": response.status if response else None,
                    "error": str(exc),
                }
                journal.record(key, failure)
                failures.append(failure)
                continue
            atomic_write(path, response.body)
            journal.record(
                key,
                {
                    "state": "complete",
                    "uid": uid,
                    "url": url,
                    "status": response.status,
                    "content_type": response.content_type,
                    "path": str(path.relative_to(output)),
                    "sha256": sha256(response.body),
                },
            )
        profiles.append(profile)

    normalized_path = output / "normalized" / "profiles.json"
    write_json(
        normalized_path,
        {"format_version": 1, "resource": "profiles", "records": profiles},
    )
    return {
        "state": "complete" if not failures and len(profiles) == len(identities) else "incomplete",
        "items": len(profiles),
        "expected_items": len(identities),
        "path": str(normalized_path.relative_to(output)),
        "sha256": sha256(normalized_path.read_bytes()),
        "failures": failures,
        "source_side_effect": "Updates the requesting administrator's activity.",
    }


def export_source(
    source: str,
    output: Path,
    token: str,
    *,
    request_interval: float = 0.6,
    allow_source_side_effects: bool = False,
) -> dict[str, object]:
    source = normalize_api_url(source)
    assessment = assess(
        source,
        output,
        token,
        request_interval=request_interval,
    )
    capabilities = assessment["capabilities"]
    if not capabilities["administrative_config"]:
        raise RuntimeError(
            "The application token did not provide the administrative configuration"
        )

    journal = WorkJournal(output)
    client = HttpClient(
        f"Application {token}",
        minimum_interval=request_interval,
    )
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
    for name, relative_url, query, source_side_effect in PAGINATED_RESOURCES:
        if source_side_effect and not allow_source_side_effects:
            resources[name] = {
                "state": "skipped",
                "reason": "Set DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true to permit this request.",
                "source_side_effect": source_side_effect,
            }
            continue
        resources[name] = export_paginated(
            name=name,
            source=source,
            relative_url=relative_url,
            output=output,
            client=client,
            journal=journal,
            query=query,
        )
        if source_side_effect:
            resources[name]["source_side_effect"] = source_side_effect

    if allow_source_side_effects:
        resources["profiles"] = _export_profiles(
            source,
            output,
            client,
            journal,
        )
    else:
        resources["profiles"] = {
            "state": "skipped",
            "reason": "Set DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true to permit profile requests.",
            "source_side_effect": "Updates the requesting administrator's activity.",
        }

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
            "profiles",
        ],
        "capabilities": capabilities,
        "assets": assets,
        "resources": resources,
    }
    write_json(output / "export.json", report)
    return report
