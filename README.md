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

With the same approval, the exporter also collects the paginated delivery list
and individual delivery details. The list updates administrator activity. Each
detail request also increments that delivery's view counter. The safe default
therefore exports the CSV data without requesting these JSON views.

`DRIVERSHUB_REQUEST_INTERVAL` controls the minimum delay between requests. Keep
the default value of `0.6` seconds unless the source operator documents a
different safe request rate.

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

This command does not contact the source Hub. It exits with a nonzero status if
the manifest is invalid, a referenced file is missing, or a checksum differs.

## Plan destination identities

Create the identity and account-claim plan before any destination data is
written:

```bash
.venv/bin/drivershub-migrate plan-import
```

The command preserves each source `uid` and `userid` in its proposed target
mapping. Imported Steam and Discord IDs let users claim their existing account
by signing in again through the corresponding provider. Passwords, MFA secrets,
and sessions are not imported. Users reconnect and verify email individually
and must enroll in MFA again.

The command writes `import-plan.json` and stops with a nonzero status when it
finds duplicate internal IDs, Steam IDs, or Discord IDs. Accounts without a
Steam or Discord ID are listed as requiring manual recovery. No destination is
contacted or modified at this stage.

## Development

Run the test suite with the Python standard library:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
