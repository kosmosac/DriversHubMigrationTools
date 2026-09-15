"""Human-readable command summaries."""

from __future__ import annotations

from pathlib import Path


def _line(label: str, value: object) -> str:
    return f"{label}: {value}"


def render_assessment(report: dict[str, object], directory: Path) -> str:
    capabilities = report.get("capabilities", {})
    plugins = capabilities.get("standard_plugins", []) if isinstance(capabilities, dict) else []
    administrative = capabilities.get("administrative_config", False) if isinstance(capabilities, dict) else False
    client_config = capabilities.get("client_config", False) if isinstance(capabilities, dict) else False
    lines = [
        "Source assessment complete.",
        _line("Migration directory", directory),
        _line("Administrative configuration", "available" if administrative else "unavailable"),
        _line("Frontend configuration", "available" if client_config else "unavailable"),
        _line("Enabled standard plugins", len(plugins) if isinstance(plugins, list) else 0),
        "Next: review assessment.json, then run drivershub-migrate export.",
    ]
    return "\n".join(lines)


def render_export(report: dict[str, object], directory: Path) -> str:
    resources = report.get("resources", {})
    plugins = report.get("plugin_resources", {})
    deliveries = report.get("deliveries", {})
    lines = [
        "Source export finished.",
        _line("Migration directory", directory),
        _line("Core resource groups", len(resources) if isinstance(resources, dict) else 0),
        _line("Plugin resource groups", len(plugins) if isinstance(plugins, dict) else 0),
        _line("Delivery export available", "yes" if isinstance(deliveries, dict) and deliveries else "no"),
        "Next: run drivershub-migrate verify before planning an import.",
    ]
    return "\n".join(lines)


def render_verification(report: dict[str, object]) -> str:
    issues = report.get("export_issues", {})
    failures = report.get("failures", [])
    complete = report.get("integrity") == "valid" and report.get("export") == "complete"
    lines = [
        "Export verification " + ("passed." if complete else "did not pass."),
        _line("Integrity", report.get("integrity", "unknown")),
        _line("Export completeness", report.get("export", "unknown")),
        _line("Checked files", report.get("checked_files", 0)),
        _line("Integrity failures", len(failures) if isinstance(failures, list) else 0),
        _line("Incomplete export entries", sum(issues.values()) if isinstance(issues, dict) else 0),
    ]
    lines.append(
        "Next: run drivershub-migrate plan-import."
        if complete
        else "Next: inspect export.json and run the export again to resume incomplete work."
    )
    return "\n".join(lines)


def render_import_plan(report: dict[str, object], directory: Path) -> str:
    summary = report.get("summary", {})
    configuration = report.get("configuration", {})
    conflicts = summary.get("conflicts", 0) if isinstance(summary, dict) else 0
    complete = report.get("state") == "complete"
    lines = [
        "Import plan " + ("complete." if complete else "blocked."),
        _line("Migration directory", directory),
        _line("Accounts", summary.get("accounts", 0) if isinstance(summary, dict) else 0),
        _line("Administrators", summary.get("administrators", 0) if isinstance(summary, dict) else 0),
        _line("Claimable accounts", summary.get("claimable", 0) if isinstance(summary, dict) else 0),
        _line("Accounts requiring manual recovery", summary.get("manual_recovery_required", 0) if isinstance(summary, dict) else 0),
        _line("Identity conflicts", conflicts),
        _line("Configuration plan", configuration.get("state", "unknown") if isinstance(configuration, dict) else "unknown"),
    ]
    lines.append(
        "Next: configure the destination and run drivershub-migrate preflight-target."
        if complete
        else "Next: inspect conflicts in import-plan.json and resolve them before continuing."
    )
    return "\n".join(lines)


def render_target_preflight(report: dict[str, object]) -> str:
    bootstrap = report.get("bootstrap", {})
    collisions = report.get("collisions", [])
    state = report.get("state", "unknown")
    lines = [
        "Destination preflight complete.",
        _line("State", state),
        _line("Target mode", report.get("target_mode", "unknown")),
        _line("Source accounts", report.get("source_accounts", 0)),
        _line("Destination accounts", len(report.get("target_accounts", []))),
        _line("Internal ID collisions", len(collisions) if isinstance(collisions, list) else 0),
        _line("Bootstrap action", bootstrap.get("action", bootstrap.get("state", "unknown")) if isinstance(bootstrap, dict) else "unknown"),
    ]
    if isinstance(bootstrap, dict) and bootstrap.get("action") == "retain-as-recovery-account":
        lines.extend(
            [
                _line(
                    "Recovery UID",
                    f'{bootstrap.get("original_uid")} -> {bootstrap.get("replacement_uid")}',
                ),
                _line(
                    "Recovery member ID",
                    f'{bootstrap.get("original_userid")} -> {bootstrap.get("replacement_userid")}',
                ),
            ]
        )
    elif isinstance(bootstrap, dict) and bootstrap.get("action") == "merge-with-source-administrator":
        matched_by = bootstrap.get("matched_by", [])
        lines.append(
            _line(
                "Identity match",
                ", ".join(matched_by) if isinstance(matched_by, list) else "unknown",
            )
        )
    if state == "complete":
        lines.append("Next: the destination is ready for an import dry run.")
    elif isinstance(bootstrap, dict) and bootstrap.get("state") == "ready":
        lines.append("Next: review and approve the proposed bootstrap action in target-preflight.json.")
    else:
        lines.append("Next: resolve the destination decisions listed in target-preflight.json.")
    return "\n".join(lines)


def render_import_dry_run(report: dict[str, object], directory: Path) -> str:
    stages = report.get("stages", {})
    configuration = stages.get("configuration", {}) if isinstance(stages, dict) else {}
    accounts = stages.get("accounts", {}) if isinstance(stages, dict) else {}
    core = stages.get("core_resources", {}) if isinstance(stages, dict) else {}
    plugins = stages.get("plugin_resources", {}) if isinstance(stages, dict) else {}
    economy = stages.get("economy", {}) if isinstance(stages, dict) else {}
    deliveries = stages.get("deliveries", {}) if isinstance(stages, dict) else {}
    ready = report.get("state") == "ready"
    lines = [
        "Import dry run " + ("ready." if ready else "blocked."),
        _line("Migration directory", directory),
        _line("Target modified", "no"),
        _line("Portable backend values", configuration.get("portable_backend_values", 0)),
        _line("Destination secrets to retain or provide", len(configuration.get("protected_destination_values", []))),
        _line("Branding assets", configuration.get("branding_assets", 0)),
        _line("Accounts", accounts.get("items", 0)),
        _line("Core resource groups", len(core) if isinstance(core, dict) else 0),
        _line("Plugin resource groups", len(plugins) if isinstance(plugins, dict) else 0),
        _line("Economy resource groups", len(economy) if isinstance(economy, dict) else 0),
        _line("Deliveries", deliveries.get("baseline_items", 0)),
        _line("Deliveries using placeholders", deliveries.get("placeholder_items", 0)),
    ]
    bootstrap = report.get("bootstrap", {})
    if isinstance(bootstrap, dict):
        lines.append(_line("Bootstrap action", bootstrap.get("action", bootstrap.get("state", "unknown"))))
    lines.append(
        "Next: review import-dry-run.json before approving a writing import."
        if ready
        else "Next: resolve the blocked stage in import-dry-run.json and repeat the dry run."
    )
    return "\n".join(lines)
