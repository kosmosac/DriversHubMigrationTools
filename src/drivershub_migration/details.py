"""Resumable export of object detail endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .http import HttpClient, RequestFailed
from .storage import WorkJournal, atomic_write, sha256, write_json


def export_details(
    *,
    name: str,
    id_key: str,
    records: list[object],
    url_for: Callable[[object], str],
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
) -> dict[str, object]:
    raw_directory = output / "raw" / name / "details"
    details: list[object] = []
    failures: list[dict[str, object]] = []
    identifiers = []
    for record in records:
        if isinstance(record, dict) and id_key in record:
            identifier = record[id_key]
            if isinstance(identifier, (int, str)) and identifier not in identifiers:
                identifiers.append(identifier)

    for identifier in identifiers:
        key = f"{name}/detail/{identifier}"
        path = raw_directory / f"{id_key}-{identifier}.json"
        detail = None
        if journal.completed(key) and path.exists():
            try:
                detail = json.loads(path.read_bytes())
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = None
        url = url_for(identifier)
        if detail is None:
            try:
                response = client.get(url)
                detail = response.json()
                if not isinstance(detail, dict) or detail.get(id_key) != identifier:
                    raise ValueError(
                        f"The detail response does not match {id_key} {identifier}"
                    )
            except (RequestFailed, ValueError) as exc:
                response = exc.response if isinstance(exc, RequestFailed) else None
                failure = {
                    "state": "failed",
                    id_key: identifier,
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
                    id_key: identifier,
                    "url": url,
                    "status": response.status,
                    "content_type": response.content_type,
                    "path": str(path.relative_to(output)),
                    "sha256": sha256(response.body),
                },
            )
        details.append(detail)

    normalized_path = output / "normalized" / f"{name}-details.json"
    write_json(
        normalized_path,
        {"format_version": 1, "resource": f"{name}-details", "records": details},
    )
    return {
        "state": "complete" if not failures and len(details) == len(identifiers) else "incomplete",
        "items": len(details),
        "expected_items": len(identifiers),
        "path": str(normalized_path.relative_to(output)),
        "sha256": sha256(normalized_path.read_bytes()),
        "failures": failures,
    }
