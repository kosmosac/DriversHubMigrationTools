"""Build the lossless part of the economy import."""

from __future__ import annotations

from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _records


def build_economy_stage(directory: Path) -> tuple[str, dict[str, object]]:
    balances = _records(directory, "economy-balances")
    transactions = _records(directory, "economy-transactions")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    for row in balances:
        values = [
            _integer(row.get("userid"), "economy balance userid"),
            _integer(row.get("balance"), "economy balance"),
        ]
        statements.append(
            "INSERT INTO `economy_balance` (`userid`,`balance`) VALUES ("
            + ",".join(_sql_value(value) for value in values)
            + ");"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready",
        "balances": len(balances),
        "transactions_not_importable": len(transactions),
        "transaction_limitation": "Source API omits stored timestamps and internal note values.",
        "database_time_zone": "+00:00",
    }
