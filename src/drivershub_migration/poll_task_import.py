"""Build imports for polls, votes, and tasks exposed by the source API."""

from __future__ import annotations

from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _compressed, _records, _timestamp


POLL_CONFIG_KEYS = (
    "max_choice", "allow_modify_vote", "show_stats", "show_stats_before_vote",
    "show_voter", "show_stats_when_ended",
)


def _userid(value: object, field: str) -> int:
    if not isinstance(value, dict):
        raise ValueError(f"{field} is not an object")
    return _integer(value.get("userid"), f"{field}.userid")


def build_poll_task_stage(directory: Path) -> tuple[str, dict[str, object]]:
    polls = _records(directory, "polls-details")
    tasks = _records(directory, "tasks-details")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    choices = votes = 0
    for row in polls:
        pollid = _integer(row.get("pollid"), "pollid")
        config = row.get("config")
        if not isinstance(config, dict):
            raise ValueError(f"Poll {pollid} has no configuration")
        serialized_config = ",".join(
            str(_integer(config.get(key), f"poll config {key}"))
            if key == "max_choice" else str(int(bool(config.get(key))))
            for key in POLL_CONFIG_KEYS
        )
        values = [
            pollid, _userid(row.get("creator"), "poll creator"),
            row.get("title") if isinstance(row.get("title"), str) else "",
            _compressed(row.get("description"), "poll description"),
            serialized_config, _integer(row.get("orderid"), "poll orderid"),
            bool(row.get("is_pinned")),
            _integer(row.get("end_time"), "poll end_time", optional=True),
            _timestamp(row.get("timestamp"), "poll timestamp"),
        ]
        statements.append(
            "INSERT INTO `poll` (`pollid`,`userid`,`title`,`description`,`config`,`orderid`,`is_pinned`,`end_time`,`timestamp`) VALUES ("
            + ",".join(_sql_value(value) for value in values) + ");"
        )
        poll_choices = row.get("choices")
        if not isinstance(poll_choices, list):
            raise ValueError(f"Poll {pollid} has no choices array")
        for choice in poll_choices:
            if not isinstance(choice, dict):
                raise ValueError(f"Poll {pollid} has an invalid choice")
            choiceid = _integer(choice.get("choiceid"), "poll choiceid")
            statements.append(
                "INSERT INTO `poll_choice` (`choiceid`,`pollid`,`orderid`,`content`) VALUES ("
                + ",".join(_sql_value(value) for value in [
                    choiceid, pollid, _integer(choice.get("orderid"), "poll choice orderid"),
                    choice.get("content") if isinstance(choice.get("content"), str) else "",
                ]) + ");"
            )
            choices += 1
            voters = choice.get("voters")
            if voters is None:
                continue
            if not isinstance(voters, list):
                raise ValueError(f"Poll {pollid} has invalid voter data")
            for voter in voters:
                userid = _userid(voter, "poll voter")
                statements.append(
                    "INSERT INTO `poll_vote` (`pollid`,`choiceid`,`userid`,`timestamp`) VALUES ("
                    f"{pollid},{choiceid},{userid},0);"
                )
                votes += 1

    for row in tasks:
        taskid = _integer(row.get("taskid"), "taskid")
        creator = _userid(row.get("creator"), "task creator")
        assigned = row.get("assign_to")
        if not isinstance(assigned, list):
            raise ValueError(f"Task {taskid} has no assignment list")
        assign_to = "," + ",".join(str(_integer(value, "task assignment")) for value in assigned) + ","
        values = [
            taskid, creator,
            row.get("title") if isinstance(row.get("title"), str) else "",
            _compressed(row.get("description"), "task description"),
            _integer(row.get("priority"), "task priority"),
            _integer(row.get("bonus"), "task bonus"), 0,
            _timestamp(row.get("due_timestamp"), "task due timestamp"),
            _timestamp(row.get("remind_timestamp"), "task reminder timestamp"),
            _integer(row.get("recurring"), "task recurring"),
            _integer(row.get("assign_mode"), "task assignment mode"), assign_to,
            bool(row.get("mark_completed")),
            row.get("mark_note") if isinstance(row.get("mark_note"), str) else "",
            _integer(row.get("mark_timestamp"), "task mark timestamp", optional=True),
            bool(row.get("confirm_completed")),
            row.get("confirm_note") if isinstance(row.get("confirm_note"), str) else "",
            _integer(row.get("confirm_timestamp"), "task confirm timestamp", optional=True),
        ]
        statements.append(
            "INSERT INTO `task` (`taskid`,`userid`,`title`,`description`,`priority`,`bonus`,`create_timestamp`,`due_timestamp`,`remind_timestamp`,`recurring`,`assign_mode`,`assign_to`,`mark_completed`,`mark_note`,`mark_timestamp`,`confirm_completed`,`confirm_note`,`confirm_timestamp`) VALUES ("
            + ",".join(_sql_value(value) for value in values) + ");"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready", "polls": len(polls), "poll_choices": choices,
        "poll_votes": votes, "poll_vote_placeholder_timestamps": votes,
        "tasks": len(tasks), "task_placeholder_create_timestamps": len(tasks),
        "database_time_zone": "+00:00",
    }
