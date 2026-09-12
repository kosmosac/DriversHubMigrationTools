"""Initial read-only source export."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urljoin

from .assess import assess, normalize_api_url
from .details import export_details
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

PLUGIN_RESOURCES = (
    ("announcement", "announcements", "announcements/list", "announcementid", None, {"order_by": "announcementid", "order": "asc"}, True),
    ("application", "applications", "applications/list", "applicationid", "applications/{id}", {"order_by": "applicationid", "order": "asc", "all_user": "true"}, True),
    ("challenge", "challenges", "challenges/list", "challengeid", "challenges/{id}", {"order_by": "challengeid", "order": "asc"}, True),
    ("downloads", "downloads", "downloads/list", "downloadsid", None, {"order_by": "downloadsid", "order": "asc"}, True),
    ("event", "events", "events/list", "eventid", "events/{id}", {"order_by": "eventid", "order": "asc"}, True),
    ("poll", "polls", "polls/list", "pollid", "polls/{id}", {"order_by": "pollid", "order": "asc"}, True),
    ("task", "tasks", "tasks/list", "taskid", "tasks?taskid={id}", {"order_by": "taskid", "order": "asc"}, False),
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


def _normalized_records(output: Path, name: str) -> list[object]:
    path = output / "normalized" / f"{name}.json"
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    records = value.get("records", []) if isinstance(value, dict) else []
    return records if isinstance(records, list) else []


def _export_plugins(
    *,
    source: str,
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
    enabled_plugins: list[str],
    allow_source_side_effects: bool,
) -> dict[str, object]:
    results: dict[str, object] = {}
    for plugin, name, list_url, id_key, detail_url, query, has_side_effect in PLUGIN_RESOURCES:
        if plugin not in enabled_plugins:
            results[plugin] = {"state": "disabled"}
            continue
        if has_side_effect and not allow_source_side_effects:
            results[plugin] = {
                "state": "skipped",
                "reason": "Set DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true to permit these requests.",
                "source_side_effect": "Updates the requesting administrator's activity.",
            }
            continue
        listing = export_paginated(
            name=name,
            source=source,
            relative_url=list_url,
            output=output,
            client=client,
            journal=journal,
            query=query,
        )
        plugin_result: dict[str, object] = {"list": listing}
        if listing["state"] == "complete" and detail_url is not None:
            records = _normalized_records(output, name)
            details = export_details(
                name=name,
                id_key=id_key,
                records=records,
                url_for=lambda identifier, template=detail_url: urljoin(
                    source, template.format(id=identifier)
                ),
                output=output,
                client=client,
                journal=journal,
            )
            plugin_result["details"] = details
            plugin_result["state"] = details["state"]
        elif listing["state"] == "complete":
            plugin_result["details"] = {
                "state": "not-required",
                "reason": "The administrative list response contains the relevant object data.",
            }
            plugin_result["state"] = "complete"
        else:
            plugin_result["state"] = "incomplete"
        if has_side_effect:
            plugin_result["source_side_effect"] = (
                "Updates the requesting administrator's activity."
            )
        results[plugin] = plugin_result

    if "division" in enabled_plugins:
        results["division"] = {
            "state": "complete",
            "definitions": "Included in the administrative backend configuration.",
            "pending": export_paginated(
                name="division-pending",
                source=source,
                relative_url="divisions/list/pending",
                output=output,
                client=client,
                journal=journal,
                query={"order_by": "logid", "order": "asc"},
            ),
        }
    else:
        results["division"] = {"state": "disabled"}

    for plugin in ("banner", "route"):
        if plugin in enabled_plugins:
            results[plugin] = {
                "state": "configuration-only",
                "reason": "No independent content collection is exposed by this plugin.",
            }
        else:
            results[plugin] = {"state": "disabled"}
    return results


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

    plugin_resources = _export_plugins(
        source=source,
        output=output,
        client=client,
        journal=journal,
        enabled_plugins=capabilities["standard_plugins"],
        allow_source_side_effects=allow_source_side_effects,
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
            "profiles",
        ],
        "capabilities": capabilities,
        "assets": assets,
        "resources": resources,
        "plugin_resources": plugin_resources,
    }
    write_json(output / "export.json", report)
    return report
