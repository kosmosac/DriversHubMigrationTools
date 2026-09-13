# Drivers Hub Migration Tools

Drivers Hub Migration Tools will transfer data from an existing Drivers Hub to
a new installation. Source access requires only the public Hub API and an
administrator account. The destination is expected to be under the operator's
control.

The project is in an early implementation stage. It currently provides a
read-only source assessment and a resumable export of the supported source
data. Destination import is not yet available.

See [DESIGN.md](DESIGN.md) for the planned migration coverage, limitations, and
implementation stages.

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

## Assess a source Hub

Create a dedicated application token in the source Hub. Give it a name that
identifies the migration and its creation date. Set the source URL, token, and
migration directory in `.env`. Then run:

```bash
.venv/bin/drivershub-migrate assess
```

Delete the application token in the source Hub after the final assessment or
export.

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

The command writes request progress and retries to the terminal while it runs.
Its final JSON report remains separate on standard output and can still be
redirected to another file.

The command reuses completed requests. It requires administrative configuration
access and currently exports:

- backend and frontend configuration;
- logo, banner, and background image;
- users who are not accepted as members;
- accepted members;
- current bans.
- announcements, applications, challenges, downloads, events, polls, and tasks;
- division definitions and pending division validations.
- deliveries as an unchanged CSV export and a normalized JSON representation.
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
manifest and all referenced files are valid. `manifest_states` separately
summarizes complete, skipped, partial, and other export entries. The command
exits with a nonzero status if the manifest is invalid, a referenced file is
missing, or a checksum differs.

## Plan destination identities

Create the identity and account-claim plan before any destination data is
written:

```bash
.venv/bin/drivershub-migrate plan-import
```

The command preserves each source `uid` and `userid` in its proposed target
mapping. Imported Steam and Discord IDs let users claim their existing account
by signing in again through the corresponding provider. An imported email
address provides a third claim method through the normal password-reset flow
when SMTP is configured. Passwords, MFA secrets, and sessions are not imported,
and users must enroll in MFA again.

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
administrator. Every existing destination account is reported for an explicit
preserve-or-merge decision. Source `uid` and `userid` values remain unchanged
in either case.

## Development

Run the test suite with the Python standard library:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
