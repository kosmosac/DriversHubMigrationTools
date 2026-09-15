# Drivers Hub Migration Tools

Drivers Hub Migration Tools transfers supported data exposed to an
administrator from an existing Drivers Hub into a new installation. It
provides resumable source assessment and export, import planning, staged
destination imports, and final destination verification. Source access
requires only the Hub's public HTTP API and a dedicated administrator
application token. The operator needs full control of the destination
installation and its MariaDB database.

The migration preserves all accessible source data without anonymizing it.
Some information—including passwords, MFA secrets, sessions, deleted records,
and data hidden behind unavailable external plugins—cannot be obtained through
the source API. Missing delivery details and economy transaction metadata use
recognizable placeholders and are designed for later optional enrichment.

See [DESIGN.md](DESIGN.md) for the coverage model and technical limitations.

The current writing import covers accounts and identities, portable
configuration and branding, exposed user state, standard-plugin content,
economy state and inventory, baseline deliveries, and their exported challenge
and pending-division relationships. Fields that the source API does not expose
are reported explicitly and receive neutral placeholder values where the
destination schema requires them.

## Workflow

The normal migration sequence is:

1. assess and export the source Hub;
2. verify the completed export;
3. create an import plan and inspect the destination;
4. run the dry-run import;
5. back up the destination and stop its writer services;
6. run every documented import stage in order;
7. verify the destination before starting the Hub.

Each command prints a concise result and the next action. Detailed JSON reports
and resumable state remain in the migration directory.

## Requirements

- Python 3.11 or newer
- the API URL of the source Hub, including its prefix
- a temporary application token created by a source Hub administrator

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
chmod 600 .env
```

Commands print short status information and the next recommended action. Their
complete reports are stored in the migration directory. Add the global
`--json` option before the command when machine-readable standard output is
required:

```bash
.venv/bin/drivershub-migrate --json verify
```

## Assess a source Hub

Create a dedicated application token in the source Hub. Give it a name that
identifies the migration and its creation date. Set the source URL, token, and
migration directory in `.env`. Then run:

```bash
.venv/bin/drivershub-migrate assess
```

Delete the application token after the final export unless you intend to run
the optional post-migration enrichment jobs. Those jobs need source API access
and can use the same dedicated token while they run.

The assessment only sends HTTP `GET` requests. It writes these files to the
selected migration directory:

- `assessment.json`: assessment results
- `work-journal.json`: persistent request state
- `raw/assessment/`: unmodified source responses

Run the same command with the same directory after an interruption. Completed
requests are reused. Use `--no-token` to inspect only public endpoints. Use
`--env-file PATH` before the `assess` command to select a different
configuration file:

```bash
.venv/bin/drivershub-migrate --env-file PATH assess
```

The migration directory contains personal and operational data. Store it on a
trusted system and retain its owner-only file permissions.

## Export supported source data

After a successful assessment, run:

```bash
.venv/bin/drivershub-migrate export
```

The command writes request progress and retries to standard error while it
runs, then prints a short result to standard output. Use the global `--json`
option to print the complete machine-readable report instead.

The command reuses completed requests. It requires administrative configuration
access and currently exports:

- backend and frontend configuration;
- logo, banner, and background image;
- users who are not accepted as members;
- accepted members;
- current bans;
- announcements, applications, challenges, downloads, events, polls, and tasks;
- division definitions and pending division validations;
- deliveries as an unchanged CSV export and a normalized JSON representation;
- Economy configuration and account balances; vehicle, garage, merchandise,
  transaction, and garage-slot data are included with source-side effects enabled.

Accepted members, detailed profiles, role history, and ban history are
available when `DRIVERSHUB_ALLOW_SOURCE_SIDE_EFFECTS=true` is set in `.env`.
The relevant list and profile requests update the requesting administrator's
activity in the source Hub. They therefore require explicit approval and are
disabled by default.

Announcements, applications, challenges, downloads, events, and polls also
update administrator activity. Their list and detail exports use the same
explicit approval. Task content and pending division validations do not require
this approval. Plugin content is exported only when the frontend configuration
reports that the corresponding standard plugin is enabled.

The upstream transaction endpoint reports inconsistent totals for some
transaction types. The exporter therefore reads each account until an actual
empty page and deduplicates the result by transaction ID.

With the same approval, the exporter also collects the paginated delivery list.
Individual delivery details require the separate
`DRIVERSHUB_ALLOW_DELIVERY_VIEW_UPDATES=true` setting because each request
increments that delivery's view counter. The safe default therefore exports the
CSV and, when activity updates are allowed, the JSON list without requesting
these detail views.

`DRIVERSHUB_REQUEST_INTERVAL` controls the minimum delay between requests. The
default value of `1.1` seconds stays below the limit of 60 requests per minute
used by some source endpoints. Use a different value only when the source
operator documents a safe request rate.

Paginated responses are stored unchanged below `raw/`. Combined representations
for later import are stored below `normalized/`. Missing branding assets do not
fail the export. `export.json` records completeness, item counts, failures, and
checksums.

The delivery list uses ascending delivery IDs. If new deliveries appear while a
long export is running, the exporter follows the increased page count and uses
the latest reported item total. Decreasing totals and missing pages remain
errors.

Enabled standard plugins are detected from the frontend configuration. The
source API does not expose its complete external-plugin list. The report marks
external-plugin detection as partial instead of treating undetected plugins as
absent.

The audit log is not exported because its endpoint does not accept application
tokens. Passwords, MFA secrets, OAuth tokens, sessions, deleted deliveries,
private user settings, and data owned only by unavailable external plugins are
also outside the accessible source data.

## Verify an export

Before transferring or importing a migration directory, verify its manifest,
files, and checksums:

```bash
.venv/bin/drivershub-migrate verify
```

This command does not contact the source Hub. `integrity` reports whether the
manifest and all referenced files are valid. `export` reports whether any
export entries are failed, incomplete, or inconsistent. `manifest_states`
summarizes all recorded states. The command exits with a nonzero status when
the integrity is invalid or the export is incomplete.

## Plan the destination import

Create the configuration, branding, identity, and account-claim plan before
any destination data is written:

```bash
.venv/bin/drivershub-migrate plan-import
```

The plan separates portable backend values from protected values that the
source API does not return. Empty protected values never replace destination
secrets. Portable frontend branding settings are kept, while the frontend
domain, API URL, plugin list, abbreviation, and generated asset keys are
derived from the destination backend during import. Available logo, banner,
and background files are included in the plan.

The command also preserves each source `uid` and `userid` in its proposed
target mapping. Imported Steam and Discord IDs let users claim their existing
account by signing in again through the corresponding provider. An imported
email address provides a third claim method through the normal password-reset
flow when SMTP is configured. Passwords, MFA secrets, and sessions are not
imported, and users must enroll in MFA again.

The command writes `import-plan.json` and stops with a nonzero status when it
finds duplicate internal IDs, Steam IDs, Discord IDs, or email addresses.
Accounts without Steam, Discord, or a valid email address are listed as
requiring manual recovery. No destination is contacted or modified at this
stage.

## Inspect the destination

The destination can be this project's preferred Drivers Hub Docker AIO
deployment or any installation of the upstream HubBackend with an accessible
MariaDB database.

For Docker AIO, set `DRIVERSHUB_TARGET_MODE=aio` and
`DRIVERSHUB_TARGET_DIRECTORY` to the initialized deployment directory. Its
MariaDB service must be running. For another installation, set
`DRIVERSHUB_TARGET_MODE=mariadb` and provide the `DRIVERSHUB_TARGET_DB_*`
connection values in `.env`. Then inspect its existing user accounts without
modifying them:

```bash
.venv/bin/drivershub-migrate preflight-target
```

The AIO adapter reads MariaDB through `docker compose exec`. The generic adapter
connects directly to MariaDB. Both write the same `target-preflight.json` and
use the same migration rules. Neither assumes fixed IDs for the destination
administrator. If the only destination account matches exactly one imported
administrator by email, Discord ID, or Steam ID, the report proposes a merge.
If no source administrator matches, it proposes new collision-free IDs that
retain the bootstrap account as an accessible recovery administrator. Multiple
destination accounts and ambiguous identity matches require a manual decision.
No account is changed by this command.

## Preview the import

After destination preflight, create a complete non-writing summary of the
planned import:

```bash
.venv/bin/drivershub-migrate dry-run-import
```

The command refreshes the destination preflight and writes
`import-dry-run.json`. It reports planned configuration, branding, accounts,
content, economy data, and deliveries. When delivery details were not exported,
the report shows how many deliveries require frontend-compatible placeholders
and can be completed by a later optional backfill. The command does not modify
the destination.

## Import accounts

The account stage is the first writing import stage. It preserves source UIDs
and member IDs. A matching bootstrap administrator keeps the destination
password and MFA enrollment. Otherwise, the bootstrap administrator is moved
to the recovery IDs shown by `preflight-target`. Imported users keep their
Steam ID, Discord ID, email address, roles, profile, join timestamp, and
selected tracker. Passwords and MFA secrets are not imported.

Create and verify a destination backup. Then stop every service that can write
to the Hub database while MariaDB remains running:

```bash
cd /path/to/DriversHubDockerAIO
docker compose stop backend bannergen db-init
cd /path/to/DriversHubMigrationTools
.venv/bin/drivershub-migrate import-accounts --approve --backup-confirmed
```

The command checks the service state, refreshes the destination preflight,
writes all account changes in one UTC database transaction, and verifies the
imported UIDs. It records completion in `import-journal.json` and refuses to
repeat a completed account stage.

Do not restart the destination Hub after this command yet. The account stage
does not import the remaining content, plugin data, economy data, or delivery
history. Keep the writer services stopped until the remaining import stages
have completed.

For a direct MariaDB destination, stop all backend writers yourself and add
`--writers-stopped` to the command. This is an explicit confirmation because
the tool cannot inspect services outside the Docker AIO deployment.

## Import configuration and branding

Update the installed command after pulling a version that adds dependencies:

```bash
.venv/bin/python -m pip install -e .
```

With the destination writer services still stopped, import the portable Hub
configuration and the exported branding assets:

```bash
.venv/bin/drivershub-migrate import-configuration \
  --approve \
  --backup-confirmed
```

The source tracker configuration is not imported. The command also retains
the destination values for Discord and OAuth, Steam, SMTP, captcha, MariaDB,
Redis, webhooks, forwarding targets, and other destination integrations.
Discord role mappings in imported roles, ranks, and applications
use matching values already present in the destination configuration or remain
empty when no destination mapping exists.

The command imports the remaining portable backend settings, frontend
appearance settings, logo, banner, and background image. It writes the JSON
file atomically and updates frontend configuration and assets in one database
transaction. Do not restart the Hub until all remaining import stages have
completed.

## Import user state

With the destination writer services still stopped, import durable state that
belongs to the imported accounts:

```bash
.venv/bin/drivershub-migrate import-user-state \
  --approve \
  --backup-confirmed
```

This imports global user notes, active bans, ban history, and role history.
Personal administrator notes cannot be attributed safely because the source
API does not identify their author; the command reports and skips them.
Sessions, MFA enrolments, and transient activity records are not imported.

## Import content

Import the self-contained content resources while the destination writers
remain stopped:

```bash
.venv/bin/drivershub-migrate import-content \
  --approve \
  --backup-confirmed
```

This stage currently imports announcements and downloads, retaining their
original IDs, authors, timestamps, ordering, visibility, and counters. Other
plugin resources, economy data, and deliveries are handled by later stages.

Import application records next:

```bash
.venv/bin/drivershub-migrate import-applications \
  --approve \
  --backup-confirmed
```

This preserves application IDs, applicants, answers, decisions, responsible
staff members, and original submission and response timestamps.

Import event and challenge definitions next:

```bash
.venv/bin/drivershub-migrate import-events-challenges \
  --approve \
  --backup-confirmed
```

Events retain attendance and votes. Challenge delivery links and completion
records are deferred until their referenced deliveries have been imported.
When an event's deleted creator is no longer identified by the source API, the
record is retained with the Hub's unknown-user identifier.

Import polls, exposed votes, and tasks next:

```bash
.venv/bin/drivershub-migrate import-polls-tasks \
  --approve \
  --backup-confirmed
```

Poll definitions, choices, and visible voter identities are retained. The API
does not expose original vote timestamps, so reconstructed votes use `0`.
Tasks retain their current workflow state, assignments, notes, and exposed
timestamps; their unavailable creation timestamp also uses `0`.

## Import economy state

Import the recoverable economy state next:

```bash
.venv/bin/drivershub-migrate import-economy \
  --approve \
  --backup-confirmed
```

Current balances and transaction views are imported. The list API does not
expose the original stored timestamp or internal transaction metadata, so
these fields use `0` and `migration-import/pending-enrichment` as recognizable
placeholders. Original transaction IDs, identifiable parties, amounts,
balances, and visible messages remain available. The optional resumable
enrichment operation documented below can retrieve the timestamps while the
source Hub remains reachable.

Import the exported economy inventory after balances and transactions:

```bash
.venv/bin/drivershub-migrate import-economy-inventory \
  --approve \
  --backup-confirmed
```

This restores trucks, garage slots, and merchandise when present in the
export. Garage-slot purchase prices and merchandise sale prices are not exposed
by the source API and therefore use `0`; all exposed identifiers, ownership,
state, and timestamps are retained.

## Import baseline deliveries

Import the delivery rows with verified Unix timestamps next:

```bash
.venv/bin/drivershub-migrate import-deliveries \
  --approve \
  --backup-confirmed
```

The list API is the authoritative baseline when the independently collected
CSV snapshot differs. Core delivery values and list metadata are preserved.
The detail payload contains a recognizable, frontend-renderable placeholder and
`dlog_meta.note` contains `migration-import/pending-detail-enrichment`. This
keeps delivery pages usable while allowing optional detail backfill to identify
and safely replace placeholders later.

## Import dependent relationships

After deliveries exist, restore their exported relationships:

```bash
.venv/bin/drivershub-migrate import-relationships \
  --approve \
  --backup-confirmed
```

This restores challenge delivery records, challenge completions, and pending
division requests. Every referenced delivery must exist in the baseline
import. Where the source API omits a relationship timestamp, the referenced
delivery's verified Unix timestamp is used; pending division requests remain
explicitly unprocessed.

## Verify and start the destination

Keep the writer services stopped and verify the completed import against the
destination database:

```bash
.venv/bin/drivershub-migrate verify-target
```

This compares the imported table counts with the completed stage journal and
checks delivery, challenge, and division relationships for missing referenced
records. It writes the detailed result to `target-verification.json`. Do not
start the Hub when the command reports a mismatch or integrity violation.

After a successful verification, start the Docker AIO services:

```bash
cd /path/to/DriversHubDockerAIO
docker compose up -d
```

## Optional post-migration enrichment

The destination may remain online while the following jobs run. Both jobs are
resumable: progress and source responses are stored below `enrichment/` in the
migration directory, completed work is skipped, and destination rows are
updated only while they still carry the exact migration marker. `--limit N`
can restrict a run to `N` source requests. During a run, the commands show
completed work, percentage, elapsed time, and an estimated remaining time.

Delivery details and telemetry can be restored individually:

```bash
.venv/bin/drivershub-migrate backfill-delivery-details --approve
```

This requires `DRIVERSHUB_ALLOW_DELIVERY_VIEW_UPDATES=true`, because every
detail request increments the corresponding delivery's view counter on the
source Hub. A deleted or temporarily unavailable source delivery remains
usable with its migration placeholder. A definitive `404` is marked
`migration-import/detail-unavailable`; transient failures remain pending and
can be retried later.

Economy transaction timestamps can be restored from the source CSV exports:

```bash
.venv/bin/drivershub-migrate enrich-economy-transactions --approve
```

Set `DRIVERSHUB_SOURCE_TIMEZONE` to the IANA time zone used by the source
server, for example `Europe/Berlin`. The CSV contains local timestamps without
an offset, and choosing the wrong zone would write incorrect Unix timestamps.
Timestamps in a repeated or nonexistent daylight-saving transition are left
unchanged because the CSV cannot identify a unique instant.
The source endpoint allows only three requests per minute, so this job waits at
least 20.5 seconds between requests and can take a long time. It also requires
many requests for a Hub with numerous accounts and a long history. The source
API does not expose the original internal transaction note. Successfully
matched rows receive `migration-import/internal-note-unavailable`; after every
source window has been checked, wholly unmatched rows are marked
`migration-import/enrichment-unavailable` instead of remaining pending.

Then verify login and account claiming, configuration and branding, recent
deliveries, applications, events, challenges, and economy balances in the Web
UI. Keep the pre-import database backup until these checks are complete.

## License

Drivers Hub Migration Tools is developed by
[Kosmos](https://kosmos.ac) and licensed under the GNU Affero General Public
License v3.0 or later. See [LICENSE](LICENSE).

Drivers Hub is a separate upstream project developed by
[CharlesWithC](https://charlws.com). This repository contains migration tooling
and does not redistribute the Drivers Hub applications.

## Development

Run the test suite with the Python standard library:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
