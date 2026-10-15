# Validation — v0.6 candidate, 15 October 2026

## Passed locally

- **32 backend tests passed on SQLite and again on PostgreSQL 16**. They cover call/consent/budget invariants, concurrent reservations/calendar edits, recording expiry and deletion failures, owner device pairing/proofs/replay/logout/revocation, legacy-device migration, keyring reads, production configuration guards, body limits, throttling and log redaction.
- Google REST adapter tests use mocked HTTP responses: conflict preview, configured-calendar allowlist, If-Match/stale ETags, transient failures, no mutation without confirmation, and reconciliation of an insert whose response was lost. No live Google account was accessed.
- **12 original supplied policy simulator tests passed** in the private workspace. The uploaded handoff documents/simulator are excluded from the public repository; the new backend tests independently exercise the relevant invariants.
- PostgreSQL migration upgrade, schema comparison, downgrade and re-upgrade passed. A dump/restore smoke check into a separate disposable database passed.
- Non-root/read-only production-mode container smoke passed with real PostgreSQL: readiness, development docs disabled, unauthenticated rejection, pairing, signed budget/status access, live-call gating and logout revocation.
- Backend Docker image built successfully. Caddy configuration validation passed. Six CI actions are pinned to verified upstream commit SHAs.
- Android `assembleDebug`, `assembleRelease` and `lintDebug` passed. Release shrinking/obfuscation succeeded. Lint reports **0 errors and 8 dependency-update warnings**.
- Ruff checks and formatting passed. TestClient emits one dependency deprecation warning; tests pass.

## Artifacts and limits

Debug APK is development-signed. Release APK is **unsigned** because no owner signing key was supplied. It must be signed and tested on the target device before distribution. There was no emulator UI or physical-phone session.

No paid service was activated. No production host/domain, real carrier/provider, live speech pipeline, FCM sender, attended media bridge, actual Google OAuth grant, provider purge or invoice reconciliation was tested. A local database restore is not an off-host encrypted-backup recovery drill. These results do not establish production calling readiness or an operating-cost guarantee.

GitHub workflow execution, if available, is reported separately in the draft PR/checks; the results above describe the local workspace.
