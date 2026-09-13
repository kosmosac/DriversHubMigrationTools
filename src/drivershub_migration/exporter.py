"""Initial read-only source export."""

from __future__ import annotations

from datetime import datetime, timezone
import csv
from io import StringIO
import json
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode, urljoin

from .assess import assess, normalize_api_url
from .details import export_details
from .http import HttpClient, RequestFailed
from .pagination import InvalidPage, export_paginated, validate_page
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


def _export_delivery_csv(
    source: str,
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
) -> dict[str, object]:
    key = "deliveries/csv"
    raw_path = output / "raw" / "deliveries" / "export.csv"
    response = None
    if not (journal.completed(key) and raw_path.exists()):
        url = urljoin(source, "dlog/export") + "?include_ids=true"
        try:
            response = client.get(url, expect_json=False)
            if response.content_type not in {"text/csv", "application/csv"}:
                raise ValueError(
                    f"The delivery export has content type {response.content_type or 'missing'}"
                )
            response.body.decode("utf-8")
        except (RequestFailed, ValueError, UnicodeDecodeError) as exc:
            failed_response = exc.response if isinstance(exc, RequestFailed) else response
            failure = {
                "state": "failed",
                "url": url,
                "status": failed_response.status if failed_response else None,
                "error": str(exc),
            }
            journal.record(key, failure)
            return failure
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

    try:
        text = raw_path.read_text(encoding="utf-8")
        reader = csv.DictReader(StringIO(text))
        records = list(reader)
        if not reader.fieldnames:
            raise ValueError("The delivery CSV does not contain a header")
    except (OSError, UnicodeDecodeError, csv.Error, ValueError) as exc:
        return {"state": "failed", "error": str(exc)}

    normalized_path = output / "normalized" / "deliveries-csv.json"
    write_json(
        normalized_path,
        {"format_version": 1, "resource": "deliveries-csv", "records": records},
    )
    entry = journal.entry(key)
    return {
        **entry,
        "items": len(records),
        "normalized_path": str(normalized_path.relative_to(output)),
        "normalized_sha256": sha256(normalized_path.read_bytes()),
    }


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


def _export_economy_balances(
    source: str,
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
) -> dict[str, object]:
    userids = {-1000}
    for resource in ("users", "members"):
        for record in _normalized_records(output, resource):
            if isinstance(record, dict) and isinstance(record.get("userid"), int):
                userids.add(record["userid"])

    records: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    raw_directory = output / "raw" / "economy-balances"
    for userid in sorted(userids):
        key = f"economy-balances/userid/{userid}"
        path = raw_directory / f"userid-{userid}.json"
        balance = None
        if journal.completed(key) and path.exists():
            try:
                balance = json.loads(path.read_bytes())
            except (json.JSONDecodeError, UnicodeDecodeError):
                balance = None
        url = urljoin(source, f"economy/balance/{userid}")
        if balance is None:
            try:
                response = client.get(url)
                balance = response.json()
                if not isinstance(balance, dict) or not isinstance(
                    balance.get("balance"), (int, float)
                ):
                    raise ValueError("The response does not contain a balance")
            except (RequestFailed, ValueError) as exc:
                response = exc.response if isinstance(exc, RequestFailed) else None
                failure = {
                    "state": "failed",
                    "userid": userid,
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
                    "userid": userid,
                    "url": url,
                    "status": response.status,
                    "content_type": response.content_type,
                    "path": str(path.relative_to(output)),
                    "sha256": sha256(response.body),
                },
            )
        records.append({"userid": userid, **balance})

    normalized_path = output / "normalized" / "economy-balances.json"
    write_json(
        normalized_path,
        {"format_version": 1, "resource": "economy-balances", "records": records},
    )
    return {
        "state": "complete" if not failures and len(records) == len(userids) else "incomplete",
        "items": len(records),
        "expected_items": len(userids),
        "path": str(normalized_path.relative_to(output)),
        "sha256": sha256(normalized_path.read_bytes()),
        "failures": failures,
    }


def _export_partitioned_pages(
    *,
    name: str,
    source: str,
    partitions: list[tuple[str, str, str | None]],
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
    deduplicate_by: str,
    partition_field: str | None = None,
    page_size: int = 500,
) -> dict[str, object]:
    collected: dict[object, dict[str, object]] = {}
    failures: list[dict[str, object]] = []
    pages = 0
    for partition, relative_url, partition_value in partitions:
        page_number = 1
        while True:
            key = f"{name}/{partition}/page/{page_number}"
            path = (
                output
                / "raw"
                / name
                / partition
                / f"page-{page_number:06d}.json"
            )
            page = None
            if journal.completed(key) and path.exists():
                try:
                    page = validate_page(json.loads(path.read_bytes()))
                except (json.JSONDecodeError, UnicodeDecodeError, InvalidPage):
                    page = None
            url = urljoin(source, relative_url) + "?" + urlencode(
                {"page": page_number, "page_size": page_size, "order_by": deduplicate_by, "order": "asc"}
            )
            if page is None:
                try:
                    response = client.get(url)
                    page = validate_page(response.json())
                except (RequestFailed, InvalidPage) as exc:
                    response = exc.response if isinstance(exc, RequestFailed) else None
                    failure = {
                        "state": "failed",
                        "partition": partition,
                        "page": page_number,
                        "url": url,
                        "status": response.status if response else None,
                        "error": str(exc),
                    }
                    journal.record(key, failure)
                    failures.append(failure)
                    break
                atomic_write(path, response.body)
                journal.record(
                    key,
                    {
                        "state": "complete",
                        "url": url,
                        "status": response.status,
                        "content_type": response.content_type,
                        "path": str(path.relative_to(output)),
                        "sha256": sha256(response.body),
                        "items": len(page["list"]),
                    },
                )
            pages += 1
            for value in page["list"]:
                if not isinstance(value, dict) or deduplicate_by not in value:
                    failures.append(
                        {
                            "state": "invalid",
                            "partition": partition,
                            "page": page_number,
                            "error": f"A record does not contain {deduplicate_by}",
                        }
                    )
                    continue
                record = dict(value)
                if partition_field is not None:
                    record[partition_field] = partition_value
                collected.setdefault(record[deduplicate_by], record)
            if len(page["list"]) < page_size:
                break
            page_number += 1

    records = [collected[key] for key in sorted(collected)]
    normalized_path = output / "normalized" / f"{name}.json"
    write_json(
        normalized_path,
        {"format_version": 1, "resource": name, "records": records},
    )
    return {
        "state": "complete" if not failures else "incomplete",
        "partitions": len(partitions),
        "pages": pages,
        "items": len(records),
        "path": str(normalized_path.relative_to(output)),
        "sha256": sha256(normalized_path.read_bytes()),
        "failures": failures,
    }


def _export_economy(
    *,
    source: str,
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
    allow_source_side_effects: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "state": "partial",
        "configuration": "Included in the administrative backend configuration.",
        "balances": _export_economy_balances(source, output, client, journal),
    }
    inventories = (
        ("trucks", "economy/trucks/list", {"order_by": "vehicleid", "order": "asc"}),
        ("garages", "economy/garages/list", {"order_by": "garageid", "order": "asc"}),
        ("merch", "economy/merch/list", {"order_by": "itemid", "order": "asc"}),
    )
    for name, relative_url, query in inventories:
        if allow_source_side_effects:
            result[name] = export_paginated(
                name=f"economy-{name}",
                source=source,
                relative_url=relative_url,
                output=output,
                client=client,
                journal=journal,
                query=query,
            )
            result[name]["source_side_effect"] = (
                "Updates the requesting administrator's activity."
            )
        else:
            result[name] = {
                "state": "skipped",
                "reason": "Set DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true to permit this request.",
                "source_side_effect": "Updates the requesting administrator's activity.",
            }
    if allow_source_side_effects:
        balance_records = _normalized_records(output, "economy-balances")
        userids = sorted(
            {
                record["userid"]
                for record in balance_records
                if isinstance(record, dict) and isinstance(record.get("userid"), int)
            }
        )
        result["transactions"] = _export_partitioned_pages(
            name="economy-transactions",
            source=source,
            partitions=[
                (f"userid-{userid}", f"economy/balance/{userid}/transactions/list", None)
                for userid in userids
            ],
            output=output,
            client=client,
            journal=journal,
            deduplicate_by="txid",
        )
        result["transactions"]["source_side_effect"] = (
            "Updates the requesting administrator's activity."
        )
        garage_records = _normalized_records(output, "economy-garages")
        garageids = sorted(
            {
                str(record["garageid"])
                for record in garage_records
                if isinstance(record, dict) and record.get("garageid") is not None
            }
        )
        result["garage_slots"] = _export_partitioned_pages(
            name="economy-garage-slots",
            source=source,
            partitions=[
                (
                    f"garage-{index}",
                    f"economy/garages/{quote(garageid, safe='')}/slots/list",
                    garageid,
                )
                for index, garageid in enumerate(garageids, start=1)
            ],
            output=output,
            client=client,
            journal=journal,
            deduplicate_by="slotid",
            partition_field="garageid",
            page_size=250,
        )
        result["garage_slots"]["source_side_effect"] = (
            "Updates the requesting administrator's activity."
        )
        states = [
            result[key]["state"]
            for key in ("balances", "trucks", "garages", "merch", "transactions", "garage_slots")
        ]
        result["state"] = "complete" if all(state == "complete" for state in states) else "incomplete"
    else:
        for key in ("transactions", "garage_slots"):
            result[key] = {
                "state": "skipped",
                "reason": "Set DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true to permit these requests.",
                "source_side_effect": "Updates the requesting administrator's activity.",
            }
    return result


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
    request_interval: float = 1.1,
    allow_source_side_effects: bool = False,
    allow_delivery_view_updates: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    source = normalize_api_url(source)
    assessment = assess(
        source,
        output,
        token,
        request_interval=request_interval,
        progress=progress,
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
        progress=progress,
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
    if "economy" in capabilities["standard_plugins"]:
        plugin_resources["economy"] = _export_economy(
            source=source,
            output=output,
            client=client,
            journal=journal,
            allow_source_side_effects=allow_source_side_effects,
        )
    else:
        plugin_resources["economy"] = {"state": "disabled"}

    deliveries: dict[str, object] = {
        "csv": _export_delivery_csv(source, output, client, journal),
    }
    if allow_source_side_effects:
        deliveries["list"] = export_paginated(
            name="deliveries",
            source=source,
            relative_url="dlog/list",
            output=output,
            client=client,
            journal=journal,
            query={"order_by": "logid", "order": "asc"},
        )
        if (
            deliveries["list"]["state"] == "complete"
            and allow_delivery_view_updates
        ):
            deliveries["details"] = export_details(
                name="deliveries",
                id_key="logid",
                records=_normalized_records(output, "deliveries"),
                url_for=lambda identifier: urljoin(source, f"dlog/{identifier}"),
                output=output,
                client=client,
                journal=journal,
            )
            deliveries["details"]["source_side_effect"] = (
                "Increments the view counter of every requested delivery and updates "
                "the requesting administrator's activity."
            )
        elif deliveries["list"]["state"] != "complete":
            deliveries["details"] = {
                "state": "skipped",
                "reason": "The delivery list export is incomplete.",
            }
        else:
            deliveries["details"] = {
                "state": "skipped",
                "reason": (
                    "Set DRIVERSHUB_ALLOW_DELIVERY_VIEW_UPDATES=true to permit "
                    "delivery detail requests."
                ),
                "source_side_effect": (
                    "Increments the view counter of every requested delivery."
                ),
            }
        deliveries["list"]["source_side_effect"] = (
            "Updates the requesting administrator's activity."
        )
    else:
        deliveries["list"] = {
            "state": "skipped",
            "reason": "Set DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true to permit this request.",
            "source_side_effect": "Updates the requesting administrator's activity.",
        }
        deliveries["details"] = {
            "state": "skipped",
            "reason": "Set DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true to permit these requests.",
            "source_side_effect": "Increments the view counter of every requested delivery.",
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
            "deliveries",
        ],
        "capabilities": capabilities,
        "assets": assets,
        "resources": resources,
        "plugin_resources": plugin_resources,
        "deliveries": deliveries,
    }
    write_json(output / "export.json", report)
    return report
