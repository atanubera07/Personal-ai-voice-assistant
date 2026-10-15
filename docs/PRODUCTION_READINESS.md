# Production readiness — v0.6 candidate

**Status: not approved for live production calling.** This version materially hardens the prototype and adds deployment and integration code. No hosting or telephony account exists for this project yet; no provider or physical Android device has been qualified.

## Completed in this iteration

- One-use pairing, P-256 Android Keystore identity, one-use login challenge, short-lived key-bound sessions, full-request proofs, replay rejection, logout invalidation and device revocation.
- Production fails closed without PostgreSQL and a configured HTTPS origin. Legacy shared-secret login and synthetic provider endpoints are disabled outside simulation.
- Shared database-backed auth throttling, bounded body handling, no-store response headers, redacted errors, bounded proxy timeouts and database/migration readiness.
- Blocking simulator database work moved off the ASGI event loop.
- Encryption keyring for transition periods and transactional metadata/contact-fingerprint rotation.
- Google Calendar adapter: conflict preview, configured-calendar allowlist, owner confirmation, ETags/If-Match, stable insertion IDs, read-back verification, durable approved intents and retry reconciliation. Disabled until OAuth credentials are configured.
- Non-root container, Caddy/PostgreSQL Compose configuration, operations/recovery documentation, GitHub CI configuration, shrink/obfuscation-enabled Android release build and owner signing hooks.

## Verification evidence

The current verification results are recorded in [VALIDATION.md](VALIDATION.md). Checks cover both SQLite and a real disposable PostgreSQL 16 instance, migration upgrade/schema/downgrade/re-upgrade, database dump/restore smoke, Google HTTP contract tests with simulated responses, Android compilation/lint and container/proxy validation.

Google HTTP tests include a successful write followed by a lost response: retry must return the existing event rather than insert a duplicate. No actual owner Google account was accessed and no invitation was sent. Device proof tests include stolen bearer tokens, changed bodies/paths, replayed requests/challenges, logout and legacy-device migration.

## Remaining launch blockers

| Area | Required evidence or implementation |
|---|---|
| Telecom | Personal-use provider eligibility, legal receiving number, actual carrier forwarding, provider webhook/media adapter, working non-AI fallback |
| Speech/assistant | Real streaming ASR/LLM/TTS, multilingual and interruption tests, calibrated urgency classifier; general AI chat is still absent |
| Takeover | Actual Android VoIP transport and attended bridge; independently acknowledged recording stop before human audio |
| Notifications | FCM registration/sender/retry integration and measured device delivery; existing durable outbox is not push delivery |
| Privacy | Complete storage/processor inventory, provider and backup purge agreement, recording playback/deletion integration, recovery/deletion audit |
| Economics | Full provider/carrier/model/hosting quote, approved spend policy, invoice reconciliation and provider hard caps |
| Android | Physical-device runtime, accessibility, audio routes, reminder delivery, lock/assistant-role testing; background wake word remains unimplemented |
| Google | OAuth onboarding, real-account contract test, Android event browsing/edit/delete, uncertain-operation recovery UX |
| Operations | Hosting/domain, public TLS test, external monitoring/alerts, off-host encrypted backup restore drill, image digest pinning and patch cadence |
| Release security | Owner signing key, device/runtime security review, independent penetration assessment as appropriate |

## Boundaries

The Android APK remains a candidate. A successful release compilation is not real-device proof or approval to distribute. The device key is held in Android Keystore, but hardware attestation and per-signature biometric requirements are not implemented.

Automated tests do not verify provider service behavior, calendar account permissions, carrier fees, guaranteed immediate notifications, every-copy deletion, or a monthly operating budget. These must not be advertised as solved.
