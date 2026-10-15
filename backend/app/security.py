"""Device-owned P-256 signatures. Bearer tokens alone cannot access paired devices."""

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import timedelta

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .db import Challenge, Device, Pairing, RateBucket, RequestNonce
from .domain import Problem, now


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_key(value):
    try:
        key = serialization.load_der_public_key(base64.b64decode(value, validate=True))
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        return key
    except (ValueError, TypeError):
        raise Problem("INVALID_KEY", "A P-256 public key is required", 422) from None


def verify(key, signature, message):
    try:
        public_key(key).verify(
            base64.b64decode(signature, validate=True), message.encode(), ec.ECDSA(hashes.SHA256())
        )
    except (ValueError, InvalidSignature):
        raise Problem("UNAUTHORIZED", "Invalid device proof", 401) from None


class Auth:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def throttle(self, request):
        # Peer address comes from ASGI after Uvicorn's configured trusted-proxy handling.
        peer = request.client.host if request.client else "unknown"
        key = hmac.new(self.settings.jwt_secret.encode(), peer.encode(), hashlib.sha256).hexdigest()
        window = int(time.time()) // 60
        with self.db.transaction() as s:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            insert = sqlite_insert if self.db.engine.dialect.name == "sqlite" else pg_insert
            s.execute(
                insert(RateBucket)
                .values(id=key, window=window, count=0)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            row = s.execute(select(RateBucket).where(RateBucket.id == key).with_for_update()).scalar_one()
            if row.window != window:
                row.window, row.count = window, 0
            allowed = row.count < self.settings.auth_rate_limit
            if allowed:
                row.count += 1
        if not allowed:
            raise Problem("RATE_LIMITED", "Too many authentication attempts. Retry in one minute.", 429)

    def token(self, device):
        claims = {
            "sub": device.id,
            "aud": "owner",
            "iss": "personal-agent",
            "iat": now(),
            "exp": now() + timedelta(minutes=15),
            "jti": str(uuid.uuid4()),
            "ver": device.session_version,
        }
        if device.public_key:
            claims["cnf"] = digest(device.public_key)
        return {
            "access_token": jwt.encode(claims, self.settings.jwt_secret, algorithm="HS256"),
            "expires_in": 900,
            "token_type": "bearer",
        }

    def issue_pairing(self):
        token = secrets.token_urlsafe(32)
        with self.db.transaction() as s:
            s.add(Pairing(token_hash=digest(token), expires=int(time.time()) + 300, used=False))
        return token

    def enroll(self, body):
        public_key(body.public_key)
        verify(
            body.public_key,
            body.signature,
            "personal-agent-enroll-v1\n" + body.device_id + "\n" + body.pairing_token,
        )
        with self.db.transaction() as s:
            pairing = s.execute(
                select(Pairing).where(Pairing.token_hash == digest(body.pairing_token)).with_for_update()
            ).scalar_one_or_none()
            if not pairing or pairing.used or pairing.expires < time.time():
                raise Problem("INVALID_PAIRING", "Pairing token is invalid, expired or already used", 401)
            device = s.get(Device, body.device_id)
            if device and (device.public_key or not device.enabled):
                raise Problem("DEVICE_EXISTS", "Device already enrolled or revoked; use device sign-in", 409)
            pairing.used = True
            if device:
                device.public_key = body.public_key
                device.session_version += 1
            else:
                device = Device(
                    id=body.device_id, public_key=body.public_key, enabled=True, session_version=0
                )
                s.add(device)
            return self.token(device)

    def challenge(self, device_id):
        with self.db.transaction() as s:
            device = s.get(Device, device_id)
            if not device or not device.enabled or not device.public_key:
                raise Problem("UNAUTHORIZED", "Device is not enrolled or has been revoked", 401)
            row = Challenge(
                id=str(uuid.uuid4()),
                device_id=device_id,
                nonce=secrets.token_urlsafe(32),
                expires=int(time.time()) + 60,
                used=False,
            )
            s.add(row)
            return {"id": row.id, "nonce": row.nonce, "expires_in": 60}

    def session(self, body):
        with self.db.transaction() as s:
            row = s.execute(
                select(Challenge).where(Challenge.id == body.challenge_id).with_for_update()
            ).scalar_one_or_none()
            device = s.get(Device, body.device_id)
            if (
                not row
                or row.device_id != body.device_id
                or row.used
                or row.expires < time.time()
                or not device
                or not device.enabled
            ):
                raise Problem("UNAUTHORIZED", "Device challenge is invalid or expired", 401)
            verify(
                device.public_key, body.signature, "personal-agent-session-v1\n" + row.id + "\n" + row.nonce
            )
            row.used = True
            return self.token(device)

    def owner(self, request):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise Problem("UNAUTHORIZED", "Owner authentication required", 401)
        token = header[7:]
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=["HS256"],
                audience="owner",
                issuer="personal-agent",
                options={"require": ["exp", "iat", "sub", "aud", "iss", "jti", "ver"]},
            )
            with self.db.transaction() as s:
                device = s.get(Device, claims["sub"])
                if not device or not device.enabled or device.session_version != claims["ver"]:
                    raise ValueError()
                if device.public_key:
                    if claims.get("cnf") != digest(device.public_key):
                        raise ValueError()
                    timestamp = request.headers.get("x-device-timestamp", "")
                    nonce = request.headers.get("x-device-nonce", "")
                    if abs(time.time() - int(timestamp)) > 60 or not 20 <= len(nonce) <= 100:
                        raise ValueError()
                    target = request.scope.get("raw_path", request.url.path.encode()).decode("ascii")
                    if request.scope.get("query_string"):
                        target += "?" + request.scope["query_string"].decode("ascii")
                    message = "\n".join(
                        [
                            "personal-agent-request-v1",
                            request.method,
                            target,
                            request.scope["body_digest"],
                            digest(token),
                            timestamp,
                            nonce,
                        ]
                    )
                    verify(device.public_key, request.headers.get("x-device-signature", ""), message)
                    s.add(RequestNonce(id=digest(device.id + ":" + nonce), expires=int(time.time()) + 120))
                    s.flush()
                elif not self.settings.simulation:
                    raise ValueError()
                return device.id
        except (jwt.PyJWTError, ValueError, KeyError, IntegrityError):
            raise Problem(
                "UNAUTHORIZED", "Expired, revoked, replayed or invalid device session", 401
            ) from None

    def cleanup(self):
        with self.db.transaction() as s:
            epoch = int(time.time())
            for model in (RequestNonce, Challenge, Pairing):
                s.execute(delete(model).where(model.expires < epoch))
            s.execute(delete(RateBucket).where(RateBucket.window < epoch // 60 - 60))
