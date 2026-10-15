# Device authentication protocol v1

All production traffic uses HTTPS. Only a private signing key held in Android Keystore can authenticate a paired device. Hardware attestation and a separate biometric operation for every signature are not implemented; compromise of an unlocked owner app/device remains a risk requiring device validation.

## Pairing

An operator runs `python -m app.admin pair` on the secured backend host. A random 256-bit token is stored only as SHA-256, expires in five minutes and can be consumed once. The app generates a P-256 keypair and submits:

`POST /v1/auth/enroll`: `device_id`, `pairing_token`, `public_key` (Base64 DER SubjectPublicKeyInfo), `signature` (Base64 DER ECDSA/SHA-256).

Signed UTF-8 bytes, no trailing newline:

```
personal-agent-enroll-v1
<device_id>
<pairing_token>
```

The server validates proof of the submitted key and atomically consumes the pairing token. Existing prototype devices with no public key may upgrade, invalidating old sessions. Existing paired or revoked identities cannot be overwritten.

## Sign-in

`POST /v1/auth/challenge` with `device_id` returns a one-minute challenge ID and nonce. Sign:

```
personal-agent-session-v1
<challenge_id>
<nonce>
```

Send `device_id`, `challenge_id`, `signature` to `/v1/auth/device-session`. Challenges are consumed once. Session JWTs expire in 15 minutes and bind the device ID, public-key digest, issuer, audience and session version.

## Every owner request

Use `Authorization: Bearer <JWT>`, `X-Device-Timestamp` (integer Unix seconds), `X-Device-Nonce` (unique random string, 20–100 characters), and `X-Device-Signature`.

Sign these UTF-8 lines, no trailing newline:

```
personal-agent-request-v1
<uppercase HTTP method>
<raw URL-encoded path, plus ?query when present>
<SHA-256 hex of exact body bytes; empty body uses SHA-256 of empty bytes>
<SHA-256 hex of JWT string>
<timestamp header exactly as sent>
<nonce>
```

The server checks a ±60-second clock window, device status, session version, key binding and signature, then atomically inserts a device-scoped nonce. Replays fail even across workers. Keep device clock synchronization enabled. Retries need a new nonce/signature while preserving business idempotency keys and proposal IDs.

`POST /v1/auth/logout` increments the device's session version; all its current JWTs become invalid. It does not revoke the enrollment key, so the device can sign in again. `DELETE /v1/auth/devices/{device_id}` or operator `app.admin revoke --device-id ...` disables the device entirely.

## Throttling and cleanup

Authentication attempts share a PostgreSQL bucket per trusted peer IP: 20/minute. Raw IP addresses are not stored. Only accept forwarded client/protocol headers from a controlled reverse proxy. The supplied Compose service has no published API port; its wildcard forwarded trust is appropriate only while that isolated deployment topology remains intact.

Run `python -m app.admin cleanup` at least hourly to remove expired challenges, replay records, pairing tokens and old throttle buckets. This must not be scheduled on an untrusted host with production credentials.
