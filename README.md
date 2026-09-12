# Drivers Hub Migration Tools

Drivers Hub Migration Tools will transfer data from an existing Drivers Hub to
a new installation. Source access requires only the public Hub API and an
administrator account. The destination is expected to be under the operator's
control.

The project is in an early implementation stage. It currently provides a
read-only source assessment and an initial export of backend configuration,
frontend configuration, and branding assets. Other source data and destination
import are not yet available.

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

## Export configuration and branding

After a successful assessment, run:

```bash
.venv/bin/drivershub-migrate export
```

The command reuses completed assessment requests. It requires administrative
configuration access and downloads the three branding assets when they exist.
Missing assets are recorded as unavailable and do not fail the export. The
result is stored in `export.json` and `raw/branding/`.

Enabled standard plugins are detected from the frontend configuration. The
source API does not expose its complete external-plugin list. The report marks
external-plugin detection as partial instead of treating undetected plugins as
absent.

## Development

Run the test suite with the Python standard library:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
