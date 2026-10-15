# Deployment and operations

No production infrastructure has been provisioned. These steps are a deployment runbook for the owner once hosting and a domain are selected. Do not route real callers until the integration gates in `PRODUCTION_READINESS.md` pass.

## Prerequisites

- A supported Linux host with Docker Compose v2, encrypted host storage, security updates and restricted administrative access.
- A domain pointing at the host, ports 80/443 available for Caddy HTTPS, monitoring and an approved hosting budget.
- Independent random secrets and a recovery plan for the database, metadata encryption key and Android signing key. Never put credentials in GitHub, an APK, shell history or support logs.

Copy `deploy/example.env` to `deploy/.env`, set mode 0600 and fill every required value. Use a random URL-safe database password (so its URL encoding is unambiguous). Generate `DATA_KEY` with `Fernet.generate_key()` and other secrets with a cryptographically secure generator. Template values are not deployable credentials.

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml build api
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d db
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile ops run --rm migrate
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d api proxy
```

Inspect `/health` for process health and `/ready` for database connectivity and expected migration revision. Readiness failure must prevent traffic. The API runs without root, with a read-only root filesystem, dropped capabilities, bounded request size/concurrency and no access logs. Only the HTTPS proxy publishes a port. Configure firewall policy to preserve this boundary; do not expose the database or API port.

The example uses major-version container tags. Before launch, resolve tested image digests, record them in deployment configuration and establish a patching cadence. Hosting costs, certificate issuance and public DNS have not been verified here.

If building inside a managed proxy environment, supply its combined CA bundle as the BuildKit secret `proxy_ca`. The Dockerfile uses it only during dependency installation. Never disable certificate verification or copy a private proxy credential into an image.

## Pairing, revocation and release signing

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m app.admin pair
```

Enter the token only in the owner Android app. Treat access to this operator command as owner authority. Revoke a lost device with `python -m app.admin revoke --device-id ID`. Recovery requires a new device ID/key and fresh one-use pairing token; it does not recover local notes.

For a release build, set `ANDROID_KEYSTORE_PATH`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, and `ANDROID_KEY_PASSWORD` in a protected build environment, then run `./gradlew assembleRelease`. Keys/passwords are read by Gradle for signing and are not application configuration. Store the signing key offline with recovery controls; losing it prevents upgrades to existing installations. Without these variables the generated release APK is deliberately unsigned. Do not distribute a debug-signed APK as production.

## Google Calendar

The real adapter is disabled by default. In Google Cloud configure an OAuth application, enable the Calendar API, and complete consent for the owner's account with offline access and `https://www.googleapis.com/auth/calendar.events`. Obtain a refresh token through a trusted OAuth client. This repository does not implement an OAuth browser callback/onboarding flow; do not paste tokens into chat or source control.

Set `CALENDAR_PROVIDER=google`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, and `GOOGLE_CALENDAR_ID` in the private server environment. Restart API after configuration. Only that calendar ID is accepted. Use a dedicated test calendar first.

The adapter refreshes access tokens in memory, checks conflicts at proposal time, performs no mutation until explicit owner confirmation, rechecks ETags, sends If-Match on edits/deletes, uses stable event IDs and reads back writes. Attendees in API proposals are explicit and writes use `sendUpdates=all`; confirmation must show all attendees. The current Android create form supplies none. The API supports edit/delete proposals; Android edit/delete event browsing is not implemented.

A confirmed request with an uncertain Google response stays `APPROVED`. `GET /v1/calendar/pending` lists unresolved approved changes; the proposing device may retry `/v1/calendar/mutation-proposals/{id}/reconcile`. Reconciliation cannot authorize an unconfirmed proposal. Stable IDs and mutation markers prevent duplicate inserts after a lost response. Stale/rejected proposals require fresh review. Do not display a successful Google update merely because confirmation was sent.

## Maintenance, monitoring and incident response

Run the Compose maintenance service hourly through a host timer:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile ops run --rm maintenance
```

Monitor readiness, process restarts, storage space, repeated auth failures, failed recording cleanup and unresolved calendar operations. The code exposes health/readiness and structured redacted failure events; a hosted metrics/alerting service is not configured. Do not enable request-body, authorization-header, audio or transcript logging. Error responses include a request ID; server logs include only that ID and the exception class.

The recorder component is not connected to live media. Once qualified, run `app.maintenance --recording-root /PRIVATE/PATH` hourly and alert on nonzero exit. Keep audio outside database backups and prohibit unapproved vendor copies. A local deletion receipt proves only local-object absence, not deletion from a provider or backup.

On a suspected credential compromise: disable affected devices, rotate JWT secrets to invalidate all sessions, revoke/replace Google refresh tokens as necessary, preserve redacted metadata for investigation, and keep live call routing disabled until the provider fallback is independently verified.

## Backup, restoration and key rotation

Back up PostgreSQL with `pg_dump -Fc` from a secured host and encrypt the dump with a separately controlled backup key before storing it off-host. Keep `DATA_KEY`/previous keys in a separate secret manager; a database backup without the encryption key cannot restore private content. Do not back up recordings pending an agreed all-copy retention policy. Agree a bounded metadata backup retention period: deleting a summary from the live database does not automatically erase retained backups.

Restore to an isolated empty PostgreSQL database using `pg_restore --exit-on-error`, run migrations, check readiness, decrypt known test records, revoke restored device sessions, and verify deletion tombstones before reopening access. Never restore over the live database during an incident without a reviewed recovery plan. A local schema dump/restore smoke test was performed; this is not an off-host encrypted-backup or disaster-recovery exercise.

For metadata key rotation, put the new key in `DATA_KEY`, retain old keys in comma-separated `PREVIOUS_DATA_KEYS`, then run `python -m app.admin rotate-metadata`. Reads can decrypt older keys during migration, and contact matching accepts old fingerprints. Rotation rewrites metadata and contact fingerprints transactionally. Do not remove old keys until recording files and retained backups have been addressed; the metadata command does not re-encrypt those files.

Before application upgrades, take and verify a backup, run migration checks against a restored staging copy, deploy the new image, and monitor readiness. Prefer rolling forward; database downgrades can discard newly added device security state. An older application image must not be exposed with weaker authentication as an automatic rollback.
