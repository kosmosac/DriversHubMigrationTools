"""Resumable export of paginated Drivers Hub resources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from .http import HttpClient, RequestFailed
from .storage import WorkJournal, atomic_write, sha256, write_json


class InvalidPage(ValueError):
    """Raised when a list endpoint does not return the expected page schema."""


def validate_page(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidPage("The response is not a JSON object")
    if not isinstance(value.get("list"), list):
        raise InvalidPage("The response does not contain a list")
    for key in ("total_items", "total_pages"):
        if not isinstance(value.get(key), int) or value[key] < 0:
            raise InvalidPage(f"The response contains an invalid {key}")
    return value


def export_paginated(
    *,
    name: str,
    source: str,
    relative_url: str,
    output: Path,
    client: HttpClient,
    journal: WorkJournal,
    page_size: int = 250,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw_directory = output / "raw" / name
    pages: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    expected_pages: int | None = None
    page_number = 1

    while expected_pages is None or page_number <= expected_pages:
        key = f"{name}/page/{page_number}"
        path = raw_directory / f"page-{page_number:06d}.json"
        page: dict[str, Any] | None = None
        if journal.completed(key) and path.exists():
            try:
                page = validate_page(json.loads(path.read_bytes()))
            except (json.JSONDecodeError, UnicodeDecodeError, InvalidPage):
                page = None

        parameters = dict(query or {})
        parameters.update({"page": str(page_number), "page_size": str(page_size)})
        url = urljoin(source, relative_url) + "?" + urlencode(parameters)

        if page is None:
            try:
                response = client.get(url)
                page = validate_page(response.json())
            except (RequestFailed, InvalidPage) as exc:
                response = exc.response if isinstance(exc, RequestFailed) else None
                failure = {
                    "state": "failed",
                    "url": url,
                    "status": response.status if response else None,
                    "error": str(exc),
                }
                journal.record(key, failure)
                failures.append({"page": page_number, **failure})
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
                    "total_items": page["total_items"],
                    "total_pages": page["total_pages"],
                },
            )

        if expected_pages is None:
            expected_pages = page["total_pages"]
        elif page["total_pages"] != expected_pages:
            failures.append(
                {
                    "page": page_number,
                    "state": "inconsistent",
                    "error": "total_pages changed during export",
                    "expected": expected_pages,
                    "observed": page["total_pages"],
                }
            )
            expected_pages = max(expected_pages, page["total_pages"])
        pages.append(page)
        page_number += 1

    records = [item for page in pages for item in page["list"]]
    record_path = output / "normalized" / f"{name}.json"
    normalized = {
        "format_version": 1,
        "resource": name,
        "records": records,
    }
    write_json(record_path, normalized)
    expected_items = pages[0]["total_items"] if pages else None
    state = "complete"
    pages_required = max(1, expected_pages) if expected_pages is not None else None
    if failures or pages_required is None or len(pages) != pages_required:
        state = "incomplete"
    if expected_items is not None and len(records) != expected_items:
        state = "incomplete"
        failures.append(
            {
                "state": "inconsistent",
                "error": "collected item count does not match total_items",
                "expected": expected_items,
                "observed": len(records),
            }
        )
    normalized_bytes = record_path.read_bytes()
    return {
        "state": state,
        "pages": len(pages),
        "expected_pages": expected_pages,
        "items": len(records),
        "expected_items": expected_items,
        "path": str(record_path.relative_to(output)),
        "sha256": sha256(normalized_bytes),
        "failures": failures,
    }
