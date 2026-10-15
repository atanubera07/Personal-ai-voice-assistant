# Personal AI Voice Assistant — v0.6 production candidate

Native Android (Kotlin / Compose / encrypted Room) and a FastAPI / PostgreSQL control plane for a single owner. **This is a hardened candidate, not a launched or certified production calling service.** Telecom, live speech, push delivery, device behavior and total operating costs still require integration and real-world acceptance tests.

## Implemented

- Offline encrypted tasks, notes and approximate reminders; review-before-save assistant commands; optional Android speech recognition.
- One-use, five-minute pairing tokens; Android Keystore P-256 identity; challenge sign-in; 15-minute sessions; signatures covering each authenticated request's method, target, body and token; replay prevention and server-side logout/revocation.
- PostgreSQL-backed login throttling, bounded HTTP requests, HTTPS/host enforcement, private-response cache controls, redacted errors, migration-aware readiness checks.
- Consent, call, handoff and recording state machines; signed synthetic callbacks; durable urgency events; encrypted metadata and local recording expiry component.
- Atomic spend reservations and confirmed-versus-estimated accounting, with explicit period-bound budget approvals. Provider invoice reconciliation and hard spend controls remain open.
- Calendar proposals with durable owner approval, conflict preview, ETag protection, stable event IDs, verified read-back and reconciliation after a lost response. A real Google REST adapter is implemented but **disabled until credentials are configured**; simulation remains available locally.
- Non-root container, PostgreSQL + Caddy HTTPS deployment configuration, GitHub verification workflow, migration checks, debug/release builds and signing hooks.

## Local development

Python 3.12+, JDK 17, Android SDK 35:

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
.venv/bin/pip install -e ./backend --no-deps
.venv/bin/python scripts/setup_dev.py
cd backend
set -a
source .env
set +a
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Existing v0.5 installations: preserve `.env` and run `alembic upgrade head`; do not reinitialize the database or replace `DATA_KEY`. The setup helper intentionally refuses to overwrite existing credentials.

In another terminal, load the same backend environment and issue a pairing token:

```bash
cd backend
set -a
source .env
set +a
../.venv/bin/python -m app.admin pair
```

The command prints a sensitive, single-use token. Enter it in Android Settings with the backend origin. Subsequent sign-ins leave the pairing field empty and prove possession of the device key. Existing prototype devices can upgrade using a new pairing token. Revoked devices require operator recovery; a pairing token cannot silently reactivate them.

Build and install:

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb reverse tcp:8000 tcp:8000
```

Use `http://127.0.0.1:8000` for a USB-forwarded phone or `http://10.0.2.2:8000` for an emulator. Only debug builds permit HTTP. Configure a device screen lock before opening the app. Notes are excluded from backups; losing the Keystore key may permanently lose local data.

The local `.env` uses SQLite and simulation. To create a synthetic call, load it in a terminal at the repository root and run `.venv/bin/python scripts/simulate_call.py`. This places no call and incurs no provider charges. The legacy shared-secret API exists only in simulation for test scripts; paired devices cannot use it.

## Deployment and verification

Read [operations](docs/OPERATIONS.md), [authentication protocol](docs/AUTH_PROTOCOL.md), and [readiness / validation](docs/PRODUCTION_READINESS.md).

```bash
scripts/check.sh
cd android
./gradlew assembleDebug assembleRelease lintDebug
```

Run the backend suite against a **dedicated disposable** PostgreSQL database by setting `TEST_DATABASE_URL`. Tests reset its application tables. The migration check additionally requires a database name ending `_test` and resets its entire public schema.

The GitHub workflow runs SQLite/PostgreSQL tests, migration checks, container build, Android builds and lint. It does not deploy, buy services, sign a production release, or prove real-device behavior. Release APKs remain unsigned unless the owner's signing credentials are supplied through the documented environment variables.

## Activation boundary

Production configuration disables all synthetic provider endpoints and refuses SQLite, non-HTTPS origins and incomplete Google configuration. Live phone handling remains unavailable until a legal provider demonstrates personal eligibility, forwarding, multilingual audio, attended takeover, stop-before-human recording, complete retention and fallback. A production deployment is not approval to enable unverified paid calling.
