"""Build the lossless part of the economy import."""

from __future__ import annotations

from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _records


def build_economy_stage(directory: Path) -> tuple[str, dict[str, object]]:
    balances = _records(directory, "economy-balances")
    transactions = _records(directory, "economy-transactions")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    balance_userids = [
        _integer(row.get("userid"), "economy balance userid") for row in balances
    ]
    if balance_userids:
        statements.append(
            "DELETE FROM `economy_balance` WHERE `userid` IN ("
            + ",".join(str(userid) for userid in balance_userids)
            + ");"
        )
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
    for row in transactions:
        from_user = row.get("from_user")
        to_user = row.get("to_user")
        if not isinstance(from_user, dict) or not isinstance(to_user, dict):
            raise ValueError("Economy transaction parties are invalid")
        from_userid = _integer(
            from_user.get("userid"), "transaction from userid", optional=True
        )
        to_userid = _integer(
            to_user.get("userid"), "transaction to userid", optional=True
        )
        values = [
            _integer(row.get("txid"), "transaction txid"),
            from_userid,
            to_userid,
            _integer(row.get("amount"), "transaction amount"),
            "migration-import/pending-enrichment",
            row.get("message") if isinstance(row.get("message"), str) else "",
            _integer(
                row.get("from_new_balance"),
                "transaction from balance",
                optional=True,
            ),
            _integer(
                row.get("to_new_balance"),
                "transaction to balance",
                optional=True,
            ),
            0,
        ]
        statements.append(
            "INSERT INTO `economy_transaction` (`txid`,`from_userid`,`to_userid`,`amount`,`note`,`message`,`from_new_balance`,`to_new_balance`,`timestamp`) VALUES ("
            + ",".join(_sql_value(value) for value in values)
            + ");"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready",
        "balances": len(balances),
        "transactions": len(transactions),
        "transactions_pending_enrichment": len(transactions),
        "transactions_without_identifiable_party": sum(
            1
            for row in transactions
            if isinstance(row.get("from_user"), dict)
            and isinstance(row.get("to_user"), dict)
            and row["from_user"].get("userid") is None
            and row["to_user"].get("userid") is None
        ),
        "transaction_placeholder_timestamp": 0,
        "transaction_placeholder_note": "migration-import/pending-enrichment",
        "transaction_limitation": "Source API list omits stored timestamps and internal note values.",
        "database_time_zone": "+00:00",
    }
