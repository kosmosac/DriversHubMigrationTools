# Drivers Hub Migration Tools

Drivers Hub Migration Tools transfers supported data from an existing Drivers
Hub into a new installation. Source access requires the Hub's public HTTP API
and an administrator application token. Full access to the destination and its
MariaDB database is required.

The recommended destination is
[DriversHubDockerAIO](https://github.com/kosmosac/DriversHubDockerAIO). Other
HubBackend installations with an accessible MariaDB database are also
supported.

Passwords, MFA secrets, sessions, deleted records, and data available only to
unsupported external plugins cannot be transferred. Optional post-migration
jobs can retrieve delivery details and economy transaction timestamps while
the source Hub remains reachable.

This release is tested with the Drivers Hub Backend 2.12.1 API and database
schema. The export and destination validation stop when required data or schema
elements are incompatible.

## Requirements

- Python 3.11 or newer with the `venv` module
- the API URL of the source Hub, including its prefix
- a temporary application token created by a source Hub administrator
- full access to the destination Hub and its MariaDB database

For a Docker AIO migration, running the complete workflow from a root shell is
recommended. A non-root user is suitable only when it has all required Docker,
file, and database permissions.

## Installation

On Debian and Ubuntu, install Python and the separately packaged `venv` module
first:

```bash
sudo apt install python3 python3-venv tmux
```

For a Docker AIO destination, enter a persistent root shell before cloning the
repository. The import needs Docker access and must replace
`config/config.json`. It also updates reports and journals in the migration
directory. Using the same privileged user for installation, export, import,
and enrichment prevents mixed file ownership and avoids adding `sudo` to every
individual command. Remain in this shell until the migration work is complete.
Skip `sudo -i` when the current user already has every required permission.

Then install the Migration Tools:

```bash
sudo -i
git clone https://github.com/kosmosac/DriversHubMigrationTools.git
cd DriversHubMigrationTools
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

## Configuration

Set the source and migration directory in `.env`:

```dotenv
DRIVERSHUB_SOURCE_URL=https://hub.example.com/api/
DRIVERSHUB_APPLICATION_TOKEN=replace-with-the-source-token
DRIVERSHUB_MIGRATION_DIRECTORY=migrations/example
```

Create a dedicated application token in the source Hub for the migration. Keep
it available until any optional post-migration enrichment is complete, then
delete it in the source Hub.

For a Drivers Hub Docker AIO destination, set:

```dotenv
DRIVERSHUB_TARGET_MODE=aio
DRIVERSHUB_TARGET_DIRECTORY=/opt/DriversHubDockerAIO
```

For another HubBackend installation, set `DRIVERSHUB_TARGET_MODE=mariadb` and
configure the `DRIVERSHUB_TARGET_DB_*` values and
`DRIVERSHUB_TARGET_CONFIG_PATH` described in [.env.example](.env.example).

Set `DRIVERSHUB_EXPORT_DELIVERY_DETAILS=true` only when the initial export
should request every delivery detail. This can take many hours on a large Hub.
When left disabled, the details can be retrieved after migration with the
resumable backfill command.

Some exports, imports, and enrichment jobs can run for several hours. Start
them in a `tmux` session so that an interrupted SSH connection does not stop
the command:

```bash
tmux new -s drivershub-migration
```

Detach with `Ctrl+B`, then `D`. Reopen the session later with:

```bash
tmux attach -t drivershub-migration
```

## Migration

### 1. Export the source

Assess, export, and verify the source:

```bash
.venv/bin/drivershub-migrate export-all
```

The command is resumable. If it reports an incomplete export, correct the
reported problem and run it again.

### 2. Back up and prepare the destination

Back up the destination before any import writes. For Docker AIO, stop the
entire stack and archive the deployment directory, which contains the
database, configuration, and uploaded assets:

```bash
mkdir -p /backup
cd /opt/DriversHubDockerAIO
docker compose down
tar -czf /backup/drivershub-$(date +%Y%m%d).tar.gz \
  .env config external_plugins data
docker compose up -d mariadb
```

Direct-mode users must add `-f compose.direct.yaml` to these Docker Compose
commands.

For a direct MariaDB destination, dump the database and copy the backend
configuration:

```bash
mysqldump -u root -p drivershub > /backup/drivershub-$(date +%Y%m%d).sql
cp /path/to/config.json /backup/config-$(date +%Y%m%d).json
```

The AIO command starts only MariaDB after the backup. Keep the remaining
services stopped until the import has finished. For a direct MariaDB
destination, stop every service that can write to the Hub database while
leaving MariaDB running.

### 3. Import the migration

Return to the Migration Tools directory and run:

```bash
.venv/bin/drivershub-migrate import-all --backup-confirmed
```

`--backup-confirmed` is required only when the workflow starts writing for the
first time. If the command is interrupted, run it again; completed stages are
skipped.

For a direct MariaDB destination, use an account that can write the backend
configuration and database, and add `--writers-stopped` after stopping all
destination writers yourself.

### 4. Start and check the destination

After a successful import, start the Docker AIO services:

```bash
cd /opt/DriversHubDockerAIO
docker compose up -d
```

Verify administrator login, account claiming, configuration, branding, recent
deliveries, applications, events, challenges, and economy balances in the Web
UI. Keep the pre-import database backup until these checks are complete.

## Exported and retained data

The export includes backend and frontend configuration, branding assets,
users, members, bans, supported standard-plugin content, divisions, delivery
history, and exposed economy data. Content from a standard plugin is exported
only when that plugin is enabled on the source Hub.

Destination-specific database, Redis, Discord, Steam, SMTP, captcha, webhook,
tracker, and OAuth values are retained. Imported users keep available Steam,
Discord, TruckersMP, and email identities. Passwords, MFA enrollment, OAuth
tokens, and sessions are not transferred.

The source API does not provide deleted deliveries, original poll-vote and task
creation timestamps, internal economy transaction notes, garage-slot purchase
prices, merchandise sale prices, or private data owned only by unsupported
external plugins. These values cannot be restored exactly.

Set `DRIVERSHUB_CONVERT_PERSONAL_NOTES_TO_GLOBAL=true` to import personal
administrator notes as global administrator notes. Otherwise they are skipped.

## Reports and recovery

The combined commands print their current stage and the next action. Detailed
reports remain in the migration directory:

- `assessment.json`: detected source capabilities
- `export.json`: export coverage, counts, and failures
- `import-plan.json`: account and configuration plan
- `target-preflight.json`: destination accounts and mappings
- `import-dry-run.json`: destination validation result
- `import-journal.json`: completed import stages
- `target-verification.json`: final counts and integrity checks

When `export-all` reports an incomplete export, inspect `export.json` and run
`export-all` again. When `import-all` stops before writing, inspect
`target-preflight.json` and `import-dry-run.json`. After writing has begun,
keep all destination writers stopped, inspect the reported stage in
`import-journal.json`, correct the problem, and run `import-all` again.

The individual commands used by the combined workflows remain available for
targeted recovery:

```text
assess, export, verify, plan-import, preflight-target, dry-run-import,
import-accounts, import-configuration, import-user-state, import-content,
import-applications, import-events-challenges, import-polls-tasks,
import-economy, import-economy-inventory, import-deliveries,
import-relationships, verify-target
```

Run `drivershub-migrate COMMAND --help` for their options. Do not run an
individual writing stage out of order.

## Post-migration enrichment

The destination may remain online during both optional jobs. They are
resumable and show progress and an estimated remaining time. Use `--limit N`
to restrict a run to `N` source requests.

Delivery details and telemetry can be restored individually:

```bash
.venv/bin/drivershub-migrate backfill-delivery-details
```

Each detail requires a separate source request. Unavailable details retain a
usable placeholder; temporary failures can be retried later.

Economy transaction timestamps can be restored from the source CSV exports:

```bash
.venv/bin/drivershub-migrate enrich-economy-transactions
```

The source endpoint allows only three requests per minute. This job can
therefore take a long time for a Hub with many accounts and a long history.
The request plan excludes accounts without exported transactions and periods
before each account was created.
Timestamps that cannot be matched unambiguously remain unavailable.

## License

Drivers Hub Migration Tools is developed by
[Kosmos](https://kosmos.ac) and licensed under the GNU Affero General Public
License v3.0 or later. See [LICENSE](LICENSE).

Drivers Hub is a separate upstream project developed by
[CharlesWithC](https://charlws.com).
