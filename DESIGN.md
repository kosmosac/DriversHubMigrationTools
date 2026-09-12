# Drivers Hub Migration Tools: Design

Design and implementation plan for tools that transfer as much data as
possible from an existing Drivers Hub to a new installation.

The operator only needs an administrator account and public HTTP access to the
source Hub. Shell, file-system, and database access to the source are not
required.

The operator has full control of the destination. This includes shell,
file-system, and database access. The destination can be installed after the
source export, for example with
[DriversHubDockerAIO](https://github.com/kosmosac/DriversHubDockerAIO).

This document defines the intended complete migration workflow. It can describe
features that are not implemented yet. See `README.md` for commands that are
currently available.

## Assessment basis

This assessment uses HubBackend `v2.12.1-1-g73376a7`. API behavior can change.
The exporter must detect the actual source version, plugins, permissions, and
available endpoints.

## Architecture

Migration consists of two independent sections:

1. **Export** connects only to the source Hub and creates a complete migration
   directory from all data available to the administrator through HTTP.
2. **Import** consumes this directory later and writes it into an installation
   controlled by the operator.

The import must not require the source Hub to remain available. The normal
workflow runs the exporter on the destination host and keeps its output there
until the destination is ready. Export and import can still run on different
computers and at different times when the operator copies the directory.

The migration directory is the stable interface between both sections. An
export must remain useful even when no destination has been selected yet.
Creating a ZIP, tar file, or other package is not part of the normal workflow.

## Operator-assisted workflow

The tools do not have to automate every step. A documented manual action is
preferred when it provides at least one clear advantage:

- it avoids storing a password or long-lived session;
- it gives the operator a meaningful security decision;
- it prevents destination secrets or infrastructure values from being
  overwritten;
- it resolves an identity or data conflict that cannot be decided safely;
- it uses an existing Hub interface more reliably than emulating it;
- it makes a destructive or irreversible operation explicit.

Manual work should not be required when it only repeats data that the tool can
obtain and validate through the same API. Every manual step must state why it
exists and what the tool verifies afterward.

## Core limit

Full destination access removes many import restrictions, but it does not
remove source restrictions. The importer cannot restore data that the source
API did not expose.

Every exported resource must receive one of these classifications:

1. **Complete**: The export contains all data required for a faithful import.
2. **Reconstructable**: The importer can create a useful equivalent, but some
   source detail is missing.
3. **Record only**: The data is useful as a record but is not safe to import.
4. **Unavailable**: The source API does not expose the data.
5. **Source side effect**: Collection changes source state and requires
   explicit operator approval.

The final report must preserve these classifications. It must not describe a
reconstructed or incomplete resource as a lossless migration.

## Data fidelity

The exporter must not anonymize, pseudonymize, redact, shorten, or otherwise
alter data returned by the source Hub. This includes personal data, account
identifiers, names, email addresses, connection identifiers, free-text fields,
audit records, application answers, and delivery data. The design assumes that
the operator has the legal authority to read, store, transfer, and process the
complete data.

When the exporter creates a normalized representation for later import, it
must also retain the complete original response. Normalization must not remove
unknown fields. The manifest must identify the source endpoint and retrieval
time for each raw data set.

This rule does not apply to credentials supplied only to operate the exporter,
such as its application token or administrator session. These credentials are
not source Hub data and must not be written to the migration directory. Values
that the source API omits or masks cannot be recovered; the report must mark
them as unavailable instead of inventing or anonymizing replacements.

## Section 1: Source export

### Authentication

The preferred source credential is a dedicated application token created by
the administrator for the migration. This avoids automation of CAPTCHA, OAuth,
and MFA login flows. It also avoids giving the exporter an existing browser
session.

The operator should:

1. Create a dedicated application token in the source WebUI.
2. Give it a name that identifies the migration and creation date.
3. Store it in the exporter's local, non-versioned `.env` file.
4. Delete it immediately after the final export.

The token is only suitable when the current Hub accepts application tokens for
all endpoints in the selected export scope. Preflight must test this. If an
endpoint requires a user session, the exporter can request an existing session
token or use an interactive login flow for that part of the export.

The current password login endpoint requires a CAPTCHA response and can require
an MFA code. OAuth login also needs an interactive browser flow. These flows
should be fallback options rather than the default automation strategy.

Application tokens can read some endpoints, but they do not replace an
administrator session for every possible export. The exporter must not store
application tokens, account passwords, MFA secrets, or session tokens in the
migration directory or normal logs.

### Preflight

Before collection, the exporter must:

- verify the Hub API URL and prefix;
- identify the backend version;
- identify enabled standard and external plugins;
- distinguish supported external plugins from detected plugins for which no
  migration adapter is available;
- verify the administrator identity and effective permissions;
- probe the endpoints required by the selected export scope;
- report which endpoints accept the dedicated application token and which need
  an administrator session;
- show unavailable resources before the export starts;
- show all known source-side effects;
- estimate the number of paginated requests where possible.

Preflight must not change the source configuration or content.

An unknown, private, or otherwise unavailable external plugin must not prevent
the export of the rest of the Hub. The report must record its name, whether it
is enabled, and which related API routes or data sets could not be exported.
The migration directory must preserve this information so that the limitation
remains visible during import.

### Data collection order

The exporter should collect data in this order:

1. Hub version, status, plugins, and capabilities.
2. Editable backend configuration.
3. Frontend configuration and branding assets.
4. Roles, permissions, forms, divisions, and other configuration-based IDs.
5. Members and external users.
6. Detailed profiles and exposed user histories.
7. Current bans.
8. Standard plugin content.
9. Deliveries and delivery exports.
10. Audit data and other operational records.
11. Data from supported external plugins.

This order lets the exporter validate references while it collects dependent
objects.

### Source API observations

The current API has no complete Hub export endpoint. The exporter must combine
many paginated lists, detail endpoints, configuration endpoints, and asset
downloads.

HTTP GET does not always mean that the source remains unchanged:

- `GET /dlog/{logid}` increments the delivery view counter.
- Some authenticated list operations update the administrator's activity.

Bulk delivery-detail collection must be disabled by default. The operator must
explicitly accept the view-counter changes before the exporter uses that
endpoint for all deliveries.

The delivery detail response includes telemetry and most of the stored tracker
payload, but it removes the embedded driver object. The CSV export contains a
useful normalized representation but not the complete original database row.

### Export coverage

The following table describes the expected source coverage. Exact coverage
must be measured during preflight.

| Data | Source API coverage | Expected export |
| --- | --- | --- |
| Editable backend configuration | Administrator configuration endpoint | Portable configuration subset; protected values are blank |
| Infrastructure configuration | Not returned as an editable portable set | Record only public information; create destination values later |
| Roles, permissions, forms, divisions, and plugin settings | Included in editable configuration | Usually complete |
| Frontend configuration | Client configuration endpoint | Complete except fields normalized by the running backend |
| Logo, banner, and background image | Client asset endpoints | Complete when `client-config` is installed |
| Members and external users | Paginated lists and profiles | Current visible account state |
| Passwords | Not exposed | Unavailable |
| MFA secrets | Not exposed | Unavailable; users must enroll again |
| OAuth credentials and sessions | Not exposed | Unavailable; users must authenticate again |
| User connections | Available according to administrator permissions and privacy behavior | Current Discord, Steam, TruckersMP, and email identifiers where exposed |
| Roles and points | Available in current member state | Usually complete |
| Profile and global notes | Partly exposed | Best effort |
| Personal notes and personal settings | User-specific or incomplete | Mostly unavailable |
| Role and ban history | Partly exposed through profiles | Best effort; verify pagination and limits |
| Current bans | Administrator ban endpoints | Usually complete |
| Deliveries | Lists and CSV export; detail endpoint has side effects | Normalized export by default; richer but side-effecting export on request |
| Deleted deliveries | Not exposed | Unavailable |
| Derived delivery statistics | Summary APIs only | Reports, not complete internal state |
| Announcements | List and detail endpoints | Usually complete |
| Downloads | List and detail endpoints | Definition data; transient download links are not useful |
| Challenges | List and detail endpoints | Definitions and visible relations; verify completion coverage |
| Events | List and detail endpoints | Definitions and visible attendance or vote state |
| Polls | List and detail endpoints | Definitions, choices, and only the vote information exposed to the administrator |
| Applications | Administrator list and detail endpoints | Visible applications, answers, status, and exposed conversation data |
| Tasks | List and detail endpoints | Visible definitions and current workflow state |
| Economy | Multiple list and transaction endpoints | Coverage must be tested per resource type |
| Audit log | Paginated administrator endpoint | Exposed entries with rendered operation text |
| Notifications and activity | Primarily user-specific | Mostly unavailable |
| External plugin data | Plugin-specific | Exported only when an adapter defines a compatible contract; otherwise recorded as unavailable without failing the migration |

### Migration directory

The exporter creates a versioned directory with:

- a manifest containing exporter and export-format versions;
- the source URL, Hub version, Hub identifier, export time, and selected scope;
- a capability and permission report;
- one JSON document for each resource type;
- original source IDs on every object;
- binary branding assets as separate files;
- delivery CSV files and optional delivery-detail records;
- pagination metadata, expected totals, and collected totals;
- warnings, HTTP failures, unavailable fields, and source-side effects;
- a checksum for every exported file.

Credentials supplied to authenticate the exporter must not be included. The
current source API masks or omits protected configuration values such as
passwords, MFA secrets, OAuth tokens, CAPTCHA secrets, SMTP passwords, tracker
secrets, and Discord bot tokens. The exporter must record these fields as
unavailable. It must not replace them with fabricated or anonymized values.

The directory contains personal data. The exporter must create files and
directories with owner-only permissions. Normal logs should identify records
by stable internal references instead of repeating their contents; this must
not change or redact the exported files. If the operator transfers the
directory to another host, secure transport and storage are the operator's
responsibility; the migration tool does not need to package the directory
first.

### Export reliability

The exporter must be resumable. It must write a persistent work journal and
commit downloaded pages or objects to temporary files before marking them as
complete. Restarting the same export must continue from the last verified
checkpoint without duplicating data or discarding already verified results.

The exporter must:

- use conservative request concurrency and configurable pacing;
- honor explicit rate-limit information and `Retry-After` when available;
- use bounded retries with exponential backoff and jitter for safe requests;
- resume paginated exports without duplicating records;
- persist pagination cursors, page numbers, object IDs, checksums, and retry
  state in the work journal;
- record every failed page and object;
- verify totals supplied by the API;
- mark the whole resource incomplete if collection is incomplete;
- finish by validating checksums and internal references.

Rate limiting cannot be identified only by HTTP status. A source can respond
with `403`, `500`, another status, an HTML error page, an empty or malformed
body, a connection reset, or a timeout instead of `429`. For this reason, the
exporter must treat repeated transient or anomalous responses as possible
throttling. It must reduce its request rate and enter a longer cooldown before
retrying. It must not treat an unexpected success response as valid until its
content type and response schema pass validation.

Retries must remain bounded. Authentication failures, permission failures, and
stable validation errors must not be retried indefinitely as presumed rate
limits. When the exporter cannot distinguish throttling from a permanent
failure, it must preserve its checkpoint, pause that resource, and give the
operator enough diagnostic information to resume later. It must not invalidate
successfully exported resources.

The export is complete only after a final consistency pass. If source data
changes while pagination is in progress, the exporter must detect duplicate or
missing IDs where possible and report that the resource may not represent one
consistent point in time.

No destination-specific ID mapping occurs during export.

### Optional manual source input

The exporter may accept files that the operator downloads or copies from the
source WebUI. This is a fallback for an unavailable endpoint or an unsupported
source version, not the default workflow.

Manually copying the backend configuration does not normally improve coverage.
The WebUI receives the same protected configuration view as the administrator
API, so secrets remain blank. The exporter should retrieve this view itself and
ask for manual input only when preflight proves that automated retrieval is not
possible.

## Section 2: Destination import

### Destination assumptions

The operator controls the destination host and can:

- install a supported Hub version;
- edit its configuration files;
- stop and start its services;
- create database backups;
- run a migration container or local importer;
- give the importer temporary database access.

The preferred destination is a new, otherwise empty installation. Import into
an active or populated Hub needs a separate merge design and is not part of the
first implementation.

### Installation order

The destination does not have to exist during export. A typical import begins
as follows:

1. Validate the migration directory without a destination.
2. Select a supported destination backend version.
3. Install the destination, for example with DriversHubDockerAIO.
4. Configure destination-only values such as domains, database credentials,
   CAPTCHA, SMTP, Discord, Steam, and tracker secrets.
5. Initialize the empty destination database with the normal Hub tooling.
6. Create and test a separate emergency administrator account.
7. Stop backend services that can write to the database.
8. Back up the empty initialized destination.
9. Run the offline importer.
10. Start the Hub and perform verification.

The importer must not create the database schema independently. The normal Hub
initializer creates the schema for the selected backend version.

### Import mechanism

The first importer should run as a dedicated container or local program next to
the destination stack. It may read destination configuration and connect
directly to the destination database.

The importer must be schema-versioned. Before any write, it must compare the
actual destination schema with an explicitly supported schema. It must stop on
unknown tables, columns, or versions.

All writes for one migration stage should run in a transaction. The importer
must support a dry run, integrity checks, rollback on failure, and an import
journal. Generic SQL dump replay is not suitable because the source export is
a logical API export, not a database dump.

### Destination configuration

Portable source configuration must be merged into a fresh destination
configuration. It must not replace destination-specific values such as:

- public domains and frontend URLs;
- API prefix where it intentionally changes;
- database and Valkey connection settings;
- CAPTCHA credentials;
- SMTP credentials;
- Discord application and bot credentials;
- Steam API keys;
- tracker secrets and webhook addresses;
- deployment-specific external plugins.

Roles, permissions, forms, divisions, business rules, and compatible plugin
settings should be imported before data that references them.

The importer should generate a proposed destination configuration and a clear
diff. The operator can then approve it, edit the destination file directly, or
apply the supported parts through the WebUI. Manual review is useful here
because the operator must supply new destination credentials and decide which
external integrations to enable.

After the operator applies the configuration, the importer must read it back
and verify all values required by later import stages. The tool must not assume
that a manually edited file or WebUI operation succeeded.

### Identity strategy

The source `uid` is an internal account ID. The source `userid` is the visible
member ID. A new empty destination can preserve many of these IDs through
controlled database insertion, but preservation must never be assumed.

The emergency destination administrator and existing destination rows can
cause conflicts. The importer must create explicit mappings for every source
and destination ID even when both values are equal.

Identity evidence should be evaluated in this order:

1. Steam ID;
2. Discord ID;
3. TruckersMP ID;
4. verified email address;
5. manual operator decision.

Names and avatar URLs are not stable identities. The importer must stop on a
conflict and must not combine accounts automatically.

### Imported user accounts

Full destination access makes it possible to create account rows from exported
profiles. These accounts must initially be treated as imported and unclaimed.

- Password hashes cannot be restored.
- MFA must be disabled until the user enrolls again.
- OAuth access and refresh tokens cannot be restored.
- Existing sessions cannot be restored.
- Discord and Steam users can authenticate again through their external
  identity when the destination integration is configured correctly.
- Email users need a safe password-reset or account-claim process.

The design must be tested against all supported registration methods before an
importer creates user rows. A separate account-claim workflow may be required
to prevent account takeover and to handle changed external connections.

### Import order

After the empty destination is initialized and stopped, import in this order:

1. Portable backend configuration.
2. Frontend configuration and branding assets.
3. Role, permission, form, division, and plugin definitions.
4. Users and the source-to-destination identity map.
5. Current roles, points, profiles, and bans.
6. Independent content such as announcements and downloads.
7. Events, polls, applications, tasks, and their exported relations.
8. Challenges and their exported relations.
9. Deliveries, telemetry, divisions, and challenge references where the
   migration directory contains sufficient data.
10. Economy state where a resource-specific integrity check is available.
11. Audit and other historical records that can be mapped safely.
12. Frontend user settings that are both exported and mappable.

Each stage must resolve all referenced IDs before writing. An unresolved
reference must stop that object or stage; it must not silently point to a
different user or object.

### Deliveries

Deliveries need a dedicated importer. Replaying tracker webhooks is not a safe
migration method because it can:

- apply current business rules instead of historical rules;
- create new timestamps and IDs;
- send notifications and webhooks;
- change economy balances and challenge state;
- reject old payload formats;
- require tracker signatures or remote services.

The importer can reconstruct core delivery and metadata rows from the CSV
export and optional detail export. Exact reconstruction depends on the source
fields that were available. Missing driver payloads, deleted deliveries,
private data, and derived statistics must remain documented as gaps.

Statistics and dependent relations must be rebuilt or imported with explicit
version-specific logic. They must not be guessed.

### Content and historical state

Direct destination access can preserve more source IDs, authors, timestamps,
counters, votes, attendees, application state, and other relations than the
normal create APIs. This is only safe when the migration directory contains
the complete logical state and the importer understands the exact target
schema.

Operational APIs must not be replayed merely to populate history. Purchases,
votes, tracker submissions, role changes, and application decisions can cause
notifications, external calls, financial transactions, or new audit entries.

### Import safety

The importer must:

- require a supported empty destination by default;
- refuse to run while backend writers are active;
- require a recent destination backup;
- start with a complete dry run;
- show all planned inserts, replacements, and skipped objects;
- use transactions and rollback on failure;
- keep a source-to-destination ID map;
- keep a durable import journal;
- verify constraints and references before commit;
- never connect to or modify the source Hub;
- never overwrite destination secrets with blank exported values;
- avoid notifications, webhooks, and external API calls during import;
- make repeated execution detectable and safe;
- verify the imported state before services restart.

The following manual checkpoints are appropriate:

- approval of the generated configuration diff;
- entry of destination secrets and external service credentials;
- confirmation of identity conflicts;
- creation and verification of the emergency administrator;
- confirmation that the destination backup exists;
- confirmation that destination writer services are stopped;
- approval of the final import plan and cutover.

Routine pagination, downloads, checksums, reference mapping, database inserts,
and verification queries should remain automated.

### Post-import verification

After import:

1. Run database integrity and reference checks while the Hub is stopped.
2. Start database, Valkey, backend, and frontend services.
3. Check backend startup and database upgrade logs.
4. Verify the emergency administrator login.
5. Compare exported source counts with destination counts.
6. Inspect samples from every imported resource type.
7. Test account claiming and fresh authentication.
8. Test branding and frontend configuration.
9. Configure and test email, Discord, Steam, TruckersMP, and trackers.
10. Enable external webhooks only after all checks succeed.

The import report must list every complete, reconstructed, record-only,
skipped, and failed object.

## Cutover and delta handling

The two-section design supports a long delay between initial export and final
cutover. Data can change on the source during that time.

A later version should support a delta export based on timestamps and source
IDs where the API permits this. The final sequence is:

1. Complete and test an initial import.
2. Put the destination back into a clean import-ready state.
3. Stop or redirect tracker submissions and other writes to the source.
4. Create a final source export or supported delta export.
5. Import the final migration directory.
6. Verify the destination.
7. Change public routing.
8. Keep the source unchanged for a defined rollback period.

The first implementation can require a fresh full export and import instead of
supporting deltas.

## Remaining hard limits

Even with full destination access, the following source data cannot be restored
faithfully when the source API does not return it:

- passwords and password hashes;
- MFA secrets;
- OAuth access and refresh tokens;
- sessions and application tokens;
- deleted deliveries;
- the removed driver object in exported delivery details;
- protected configuration secrets;
- complete personal notes, notifications, activity, and private user settings;
- internal records owned only by unsupported external plugins;
- any history truncated or hidden by a source endpoint.

Some other resources may become fully importable after endpoint-by-endpoint
testing. The project must update its coverage matrix from evidence rather than
assume that a list or detail response is complete.

## Recommended implementation stages

Development should proceed in this order:

1. **Source assessment**: authenticate, detect capabilities, and produce a
   coverage report without configuration or content writes.
2. **Source exporter**: create and validate the versioned migration directory.
3. **Destination installer guidance**: define the supported clean AIO target
   and its backup and stop procedure.
4. **Configuration and branding importer**: merge portable settings and assets
   while preserving destination secrets.
5. **Identity importer and claim design**: create mapped dormant accounts and
   define safe user access recovery.
6. **Content importers**: add one resource type at a time with integrity tests.
7. **Delivery importer**: implement explicit reconstruction and clearly report
   missing source data.
8. **Plugin adapters**: support an external plugin only when it has a documented
   and testable export and import contract.

The first useful release should implement source assessment and export before
it writes any destination database.
