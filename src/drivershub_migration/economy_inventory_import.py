"""Build imports for exported economy inventory resources."""

from __future__ import annotations

from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _records, _timestamp


STATUS = {"inactive": 0, "active": 1, "require_service": -1, "scrapped": -2}


def _userid(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} is not an object")
    return _integer(value.get("userid"), f"{field}.userid", optional=optional)


def build_economy_inventory_stage(directory: Path) -> tuple[str, dict[str, object]]:
    trucks = _records(directory, "economy-trucks")
    slots = _records(directory, "economy-garage-slots")
    merch = _records(directory, "economy-merch")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    for row in slots:
        values = [
            _integer(row.get("slotid"), "garage slotid"),
            row.get("garageid") if isinstance(row.get("garageid"), str) else str(row.get("garageid", "")),
            _userid(row.get("slot_owner"), "garage slot owner"), 0,
            row.get("note") if isinstance(row.get("note"), str) else "",
            _timestamp(row.get("purchase_timestamp"), "garage purchase timestamp"),
        ]
        statements.append(
            "INSERT INTO `economy_garage` (`slotid`,`garageid`,`userid`,`price`,`note`,`purchase_timestamp`) VALUES ("
            + ",".join(_sql_value(value) for value in values) + ");"
        )
    for row in trucks:
        truck = row.get("truck")
        if not isinstance(truck, dict) or not isinstance(truck.get("id"), str):
            raise ValueError("Economy truck identifier is unavailable")
        status = row.get("status")
        if status not in STATUS:
            raise ValueError(f"Unsupported economy truck status: {status}")
        values = [
            _integer(row.get("vehicleid"), "vehicleid"), truck["id"],
            row.get("garageid") if isinstance(row.get("garageid"), str) else "",
            _integer(row.get("slotid"), "truck slotid", optional=True),
            _userid(row.get("owner"), "truck owner"),
            _userid(row.get("assignee"), "truck assignee", optional=True),
            _integer(row.get("price"), "truck price"),
            _integer(row.get("income"), "truck income"),
            _integer(row.get("service"), "truck service cost"),
            _integer(row.get("odometer"), "truck odometer"),
            row.get("damage") if isinstance(row.get("damage"), (int, float)) and not isinstance(row.get("damage"), bool) else 0,
            _timestamp(row.get("purchase_timestamp"), "truck purchase timestamp"), STATUS[status],
        ]
        statements.append(
            "INSERT INTO `economy_truck` (`vehicleid`,`truckid`,`garageid`,`slotid`,`userid`,`assigneeid`,`price`,`income`,`service_cost`,`odometer`,`damage`,`purchase_timestamp`,`status`) VALUES ("
            + ",".join(_sql_value(value) for value in values) + ");"
        )
    for row in merch:
        values = [
            _integer(row.get("itemid"), "merch itemid"),
            row.get("merchid") if isinstance(row.get("merchid"), str) else "",
            _userid(row.get("owner"), "merch owner"),
            _integer(row.get("price"), "merch purchase price"), 0,
            _timestamp(row.get("purchase_timestamp"), "merch purchase timestamp"),
        ]
        statements.append(
            "INSERT INTO `economy_merch` (`itemid`,`merchid`,`userid`,`buy_price`,`sell_price`,`purchase_timestamp`) VALUES ("
            + ",".join(_sql_value(value) for value in values) + ");"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready", "trucks": len(trucks), "garage_slots": len(slots),
        "merchandise": len(merch), "garage_slot_placeholder_prices": len(slots),
        "merchandise_placeholder_sell_prices": len(merch),
        "database_time_zone": "+00:00",
    }
