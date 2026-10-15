import hashlib
import hmac
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import timedelta

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .adapters import SimulatedCalendar
from .config import Settings
from .db import Base, Budget, Call, Database, Device, Event, Intent, Outbox, Policy
from .domain import CallState, Problem, now, require
from .google_calendar import GoogleCalendar
from .http_boundary import HttpBoundary
from .schemas import (
    Approval,
    CalendarProposal,
    Confirmation,
    Contact,
    DeviceChallenge,
    DeviceSession,
    Disclosure,
    Enrollment,
    Interpret,
    Login,
    ProviderEvent,
    Takeover,
)
from .security import Auth


def create_app(settings=None):
    settings = settings or Settings.from_env()
    settings.validate()
    db = Database(settings)
    calendar = GoogleCalendar(settings) if settings.calendar_provider == "google" else SimulatedCalendar(db)
    auth = Auth(db, settings)

    @asynccontextmanager
    async def lifespan(app):
        # Production schema is managed by Alembic, never automatic create_all.
        if settings.simulation:
            Base.metadata.create_all(db.engine)
            with db.transaction() as session:
                if session.get(Policy, "budget_lock") is None:
                    session.add(Policy(id="budget_lock", data=""))
        yield
        db.engine.dispose()
        if isinstance(calendar, GoogleCalendar):
            calendar.close()

    app = FastAPI(
        title="Personal Agent",
        version="0.6.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.simulation else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.simulation else None,
    )
    app.add_middleware(HttpBoundary, settings=settings)
    app.state.auth = auth
    app.state.db, app.state.settings = db, settings

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.detail})

    @app.exception_handler(IntegrityError)
    async def conflict_handler(request, exc):
        return JSONResponse(
            status_code=409, content={"code": "CONCURRENT_WRITE", "detail": "Refresh and retry"}
        )

    # Validation errors deliberately omit input values (secrets / speech / contact data).
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        return JSONResponse(
            status_code=422, content={"code": "INVALID_REQUEST", "detail": "Invalid request fields"}
        )

    def owner(request: Request):
        return auth.owner(request)

    def simulated():
        if not settings.simulation:
            raise Problem(
                "INTEGRATION_UNVERIFIED",
                "This capability is available only in simulation until qualified",
                503,
            )

    def budget(s, period=None):
        period = period or now().strftime("%Y-%m")
        # Single guard row serializes creation of monthly rows on PostgreSQL too.
        s.execute(select(Policy).where(Policy.id == "budget_lock").with_for_update()).scalar_one_or_none()
        row = s.execute(select(Budget).where(Budget.period == period).with_for_update()).scalar_one_or_none()
        if not row:
            row = Budget(period=period, limit=50000, confirmed=0, estimated=0, reserved=0)
            s.add(row)
            s.flush()
        return row

    def call_row(s, cid):
        row = s.execute(select(Call).where(Call.id == cid).with_for_update()).scalar_one_or_none()
        if not row or row.deleted:
            raise Problem("NOT_FOUND", "Call not found", 404)
        return row

    def view(row):
        return {
            "id": row.id,
            **row.data,
            **db.decrypt(row.private),
            "simulation": settings.simulation,
            "recording_available": False,
            "transcript": None,
        }

    def save_intent(s, kind, data, device):
        iid, nonce = str(uuid.uuid4()), secrets.token_urlsafe(32)
        data.update(
            nonce_hash=hashlib.sha256(nonce.encode()).hexdigest(),
            device=device,
            expires_at=(now() + timedelta(minutes=5)).isoformat(),
            status="PENDING",
        )
        s.add(Intent(id=iid, kind=kind, data=db.encrypt(data)))
        return {
            "id": iid,
            "nonce": nonce,
            "proposal": {k: v for k, v in data.items() if k not in {"nonce_hash", "device"}},
        }

    def confirm_intent(s, iid, kind, nonce, device):
        row = s.execute(select(Intent).where(Intent.id == iid).with_for_update()).scalar_one_or_none()
        require(row is not None and row.kind == kind, "INVALID_INTENT", "Unknown confirmation")
        data = db.decrypt(row.data)
        require(data["device"] == device, "WRONG_DEVICE", "Confirm on the proposing device")
        require(
            hmac.compare_digest(data["nonce_hash"], hashlib.sha256(nonce.encode()).hexdigest()),
            "INVALID_NONCE",
            "Invalid confirmation",
        )
        if data["status"] in {"COMPLETED", "APPROVED"}:
            return row, data
        require(data["expires_at"] > now().isoformat(), "EXPIRED_INTENT", "Review a fresh proposal")
        require(data["status"] == "PENDING", "INVALID_INTENT", "Review a fresh proposal")
        return row, data

    @app.get("/health")
    def health():
        return {"status": "ok", "simulation": settings.simulation}

    @app.post("/v1/auth/session")
    def login(body: Login, request: Request):
        auth.throttle(request)
        simulated()
        if not hmac.compare_digest(body.secret, settings.owner_secret):
            raise Problem("UNAUTHORIZED", "Invalid owner setup secret", 401) from None
        with db.transaction() as s:
            device = s.get(Device, body.device_id)
            if device and device.public_key:
                raise Problem("DEVICE_PROOF_REQUIRED", "Use device sign-in", 401)
            if device and not device.enabled:
                raise Problem("DEVICE_REVOKED", "Re-enrollment requires administrator action", 403)
            if not device:
                device = Device(id=body.device_id, enabled=True)
                s.add(device)
        return auth.token(device)

    @app.post("/v1/auth/enroll")
    def enroll(body: Enrollment, request: Request):
        auth.throttle(request)
        return auth.enroll(body)

    @app.post("/v1/auth/challenge")
    def device_challenge(body: DeviceChallenge, request: Request):
        auth.throttle(request)
        return auth.challenge(body.device_id)

    @app.post("/v1/auth/device-session")
    def device_session(body: DeviceSession, request: Request):
        auth.throttle(request)
        return auth.session(body)

    @app.post("/v1/auth/logout")
    def logout(device=Depends(owner)):
        with db.transaction() as s:
            row = s.execute(select(Device).where(Device.id == device).with_for_update()).scalar_one()
            row.session_version += 1
        return {"signed_out": True}

    @app.get("/ready")
    def ready():
        try:
            with db.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                if not settings.simulation:
                    revision = connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
                    if revision != "0003":
                        raise ValueError()
            return {"status": "ready"}
        except Exception:
            raise Problem("NOT_READY", "Database or schema is unavailable", 503) from None

    @app.delete("/v1/auth/devices/{device_id}")
    def revoke(device_id: str, device=Depends(owner)):
        with db.transaction() as s:
            row = s.get(Device, device_id)
            if row:
                row.enabled = False
        return {"revoked": True}

    @app.get("/v1/status")
    def status(device=Depends(owner)):
        return {
            "simulation": settings.simulation,
            "live_calls": False,
            "speech": False,
            "google_calendar": settings.calendar_provider == "google",
            "calendar_id": settings.google_calendar_id,
            "wake_word": "UNVERIFIED",
            "provider": "NOT_SELECTED",
            "fallback": "UNVERIFIED",
            "gates": {f"G{i}": "UNVERIFIED" for i in range(8)},
        }

    @app.post("/v1/provider/calls/events")
    async def provider_event(
        request: Request, x_signature: str = Header(default=""), x_timestamp: str = Header(default="")
    ):
        simulated()
        raw = await request.body()
        if len(raw) > 16000:
            raise Problem("PAYLOAD_TOO_LARGE", "Event exceeds maximum size", 413)
        try:
            fresh = abs(time.time() - int(x_timestamp)) < 300
        except ValueError:
            fresh = False
        expected = hmac.new(
            settings.webhook_secret.encode(), x_timestamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        if not fresh or not hmac.compare_digest(expected, x_signature):
            raise Problem("INVALID_SIGNATURE", "Invalid or expired provider signature", 401)
        try:
            event = ProviderEvent.model_validate_json(raw)
        except ValueError:
            raise Problem("INVALID_EVENT", "Invalid provider event fields", 422) from None
        return await run_in_threadpool(process_event, event, raw)

    def process_event(event, raw):
        digest = hashlib.sha256(raw).hexdigest()
        with db.transaction() as s:
            b = budget(s)  # consistent lock order across inbound transitions
            previous = s.get(Event, event.event_id)
            if previous:
                require(
                    previous.payload_hash == digest,
                    "EVENT_COLLISION",
                    "Event ID was reused with different content",
                )
                return {"call_id": previous.call_id, "duplicate": True}
            row = s.execute(
                select(Call).where(Call.provider_ref == event.provider_call_id).with_for_update()
            ).scalar_one_or_none()
            if event.type == "received":
                require(row is None, "CALL_EXISTS", "Call already exists")
                state = CallState(period=b.period)
                if b.confirmed + b.estimated + b.reserved + event.reserve_paise > b.limit:
                    state.phase = "FAILED_ROUTED"
                else:
                    state.reserve = event.reserve_paise
                    b.reserved += state.reserve
                if event.caller_number:
                    for contact in s.scalars(select(Policy).where(Policy.id.like("contact:%"))):
                        value = db.decrypt(contact.data)
                        if (
                            value["fingerprint"] in db.number_fingerprints(event.caller_number)
                            and value["enabled"]
                        ):
                            state.category = value["category"]
                row = Call(
                    id=str(uuid.uuid4()),
                    provider_ref=event.provider_call_id,
                    data=asdict(state),
                    private=db.encrypt({"caller_number": event.caller_number}),
                )
                s.add(row)
            else:
                require(row is not None, "CALL_NOT_FOUND", "Received event is required first")
                if row.deleted:
                    # Tombstone: acknowledge late callbacks without resurrecting private data.
                    s.add(Event(id=event.event_id, call_id=row.id, payload_hash=digest))
                    return {"call_id": row.id, "deleted": True}
                state = CallState(**row.data)
                if event.expected_version is not None:
                    require(state.version == event.expected_version, "STALE_VERSION", "Refresh call state")
                was_urgent = state.urgent
                row.data = state.apply(event.type, event.model_dump())
                private = db.decrypt(row.private)
                if event.type == "urgent" and not was_urgent:
                    private["urgency_reason"] = event.reason
                    s.add(Outbox(id=f"urgent:{row.id}", call_id=row.id, state="PENDING", attempts=0))
                if event.type == "ended":
                    old_budget = b if state.period == b.period else budget(s, state.period)
                    old_budget.reserved = max(0, old_budget.reserved - state.reserve)
                    old_budget.estimated += event.estimated_cost_paise
                    # Snapshot AI summary before human media, never accept human-phase content.
                    if state.processing and state.handoff not in {"OWNER_CONNECTED", "AI_LEFT"}:
                        private["summary"] = event.summary
                    row.data = {**row.data, "reserve": 0}
                if event.type == "media_ready" and state.processing:
                    private["summary"] = event.summary
                row.private = db.encrypt(private)
            s.add(Event(id=event.event_id, call_id=row.id, payload_hash=digest))
            return {
                "call_id": row.id,
                "state": row.data,
                "simulation": True,
                "fallback": "SIMULATED_ONLY" if row.data["phase"] == "FAILED_ROUTED" else None,
            }

    @app.get("/v1/calls")
    def calls(cursor: str = "", limit: int = 30, device=Depends(owner)):
        with db.transaction() as s:
            rows = list(
                s.scalars(
                    select(Call)
                    .where(Call.deleted.is_(False), Call.id > cursor)
                    .order_by(Call.id)
                    .limit(max(1, min(limit, 100)) + 1)
                )
            )
            page = rows[: max(1, min(limit, 100))]
            return {
                "items": [view(row) for row in page],
                "next_cursor": page[-1].id if len(rows) > len(page) else None,
            }

    @app.get("/v1/calls/{cid}")
    def get_call(cid: str, device=Depends(owner)):
        with db.transaction() as s:
            return view(call_row(s, cid))

    @app.delete("/v1/calls/{cid}")
    def delete_call(cid: str, device=Depends(owner)):
        with db.transaction() as s:
            row = s.get(Call, cid)
            if row and not row.deleted:
                require(
                    row.data["phase"] in {"ENDED", "FAILED_ROUTED"},
                    "CALL_ACTIVE",
                    "Wait for a trusted terminal state",
                )
                row.deleted, row.private = True, db.encrypt({})
                for notice in s.scalars(select(Outbox).where(Outbox.call_id == cid)):
                    s.delete(notice)
        return {"deleted": True, "recording": "NO_AUDIO_IN_SIMULATION"}

    @app.post("/v1/calls/{cid}/takeover-intents")
    def takeover(cid: str, body: Takeover, device=Depends(owner)):
        simulated()
        require(device == body.device_id, "WRONG_DEVICE", "Device does not match authenticated session")
        with db.transaction() as s:
            row = call_row(s, cid)
            key = "takeover:" + hashlib.sha256((device + body.idempotency_key).encode()).hexdigest()
            old = s.get(Intent, key)
            if old:
                data = db.decrypt(old.data)
                require(data["call_id"] == cid, "INTENT_COLLISION", "Key used for another call")
                raise Problem("TOKEN_ALREADY_ISSUED", "Single-use credential is not reissued")
            state = CallState(**row.data)
            row.data = state.apply("takeover", {})
            token = secrets.token_urlsafe(32)
            s.add(
                Intent(
                    id=key,
                    kind="takeover",
                    data=db.encrypt(
                        {
                            "call_id": cid,
                            "device": device,
                            "hash": hashlib.sha256(token.encode()).hexdigest(),
                            "used": False,
                            "expires": (now() + timedelta(seconds=60)).isoformat(),
                        }
                    ),
                )
            )
            return {"intent_id": key, "join_token": token, "expires_in": 60, "simulation": True}

    @app.post("/v1/simulator/takeover/{iid}/consume")
    def consume(iid: str, body: Confirmation, device=Depends(owner)):
        simulated()
        with db.transaction() as s:
            row = s.execute(select(Intent).where(Intent.id == iid).with_for_update()).scalar_one_or_none()
            require(row is not None and row.kind == "takeover", "INVALID_TOKEN", "Unknown join token")
            data = db.decrypt(row.data)
            require(
                data["device"] == device
                and not data["used"]
                and data["expires"] > now().isoformat()
                and hmac.compare_digest(data["hash"], hashlib.sha256(body.nonce.encode()).hexdigest()),
                "INVALID_TOKEN",
                "Expired, consumed, or invalid join token",
            )
            call = call_row(s, data["call_id"])
            require(call.data["phase"] == "TAKEOVER_PREP", "CALL_ENDED", "Takeover is no longer pending")
            data["used"] = True
            row.data = db.encrypt(data)
            return {"accepted": True, "media_connected": False, "simulation": True}

    @app.get("/v1/calls/{cid}/handoff-state")
    def handoff(cid: str, device=Depends(owner)):
        with db.transaction() as s:
            row = call_row(s, cid)
            return {
                "state": row.data["handoff"],
                "recording": row.data["recording"],
                "simulation": settings.simulation,
            }

    @app.get("/v1/calls/{cid}/recording-url")
    def recording_url(cid: str, device=Depends(owner)):
        with db.transaction() as s:
            call_row(s, cid)
        raise Problem("RECORDING_UNAVAILABLE", "No audio is stored by this foundation", 404)

    @app.get("/v1/notifications")
    def notifications(device=Depends(owner)):
        with db.transaction() as s:
            return {
                "items": [
                    {"id": n.id, "call_id": n.call_id, "state": n.state}
                    for n in s.scalars(select(Outbox).where(Outbox.state != "ACKNOWLEDGED"))
                ],
                "push_delivery": "NOT_CONFIGURED",
            }

    @app.post("/v1/notifications/{nid}/ack")
    def ack(nid: str, device=Depends(owner)):
        with db.transaction() as s:
            row = s.get(Outbox, nid)
            if row:
                row.state = "ACKNOWLEDGED"
        return {"acknowledged": True}

    @app.get("/v1/budget/current")
    def current_budget(device=Depends(owner)):
        with db.transaction() as s:
            b = budget(s)
            return {
                "period": b.period,
                "authorized_limit_paise": b.limit,
                "confirmed_paise": b.confirmed,
                "estimated_paise": b.estimated,
                "reserved_paise": b.reserved,
                "currency": "INR",
                "unknown_external_fees": True,
                "simulation": settings.simulation,
                "remaining_authorization_paise": max(0, b.limit - b.confirmed - b.estimated - b.reserved),
            }

    @app.post("/v1/budget/approvals")
    def approve(body: Approval, device=Depends(owner)):
        with db.transaction() as s:
            require(
                body.period == now().strftime("%Y-%m"),
                "INVALID_PERIOD",
                "Only the current billing month can be approved",
            )
            return save_intent(s, "budget", body.model_dump(), device)

    @app.post("/v1/budget/approvals/{iid}/confirm")
    def confirm_budget(iid: str, body: Confirmation, device=Depends(owner)):
        with db.transaction() as s:
            b = budget(s)
            row, data = confirm_intent(s, iid, "budget", body.nonce, device)
            if data["status"] != "COMPLETED":
                require(
                    data["period"] == b.period,
                    "INVALID_PERIOD",
                    "Billing month changed; review a fresh approval",
                )
                b.limit += data["amount_paise"]
                data["status"] = "COMPLETED"
                row.data = db.encrypt(data)
            return {"authorized_limit_paise": b.limit, "period": b.period}

    @app.get("/v1/contacts/priority")
    def contacts(device=Depends(owner)):
        with db.transaction() as s:
            return {
                "items": [
                    {
                        "id": r.id.removeprefix("contact:"),
                        **{k: v for k, v in db.decrypt(r.data).items() if k != "fingerprint"},
                    }
                    for r in s.scalars(select(Policy).where(Policy.id.like("contact:%")))
                ]
            }

    @app.put("/v1/contacts/priority/{contact_id}")
    def contact(contact_id: str, body: Contact, device=Depends(owner)):
        require(len(contact_id) <= 80, "INVALID_ID", "Contact ID too long")
        with db.transaction() as s:
            value = body.model_dump()
            value["fingerprint"] = hmac.new(
                settings.encryption_key.encode(), ("contact:" + body.number).encode(), hashlib.sha256
            ).hexdigest()
            s.merge(Policy(id="contact:" + contact_id, data=db.encrypt(value)))
        return {"saved": True}

    @app.put("/v1/disclosures/{category}")
    def disclosure(category: str, body: Disclosure, device=Depends(owner)):
        require(category in {"Family", "Friends", "Work", "Unknown"}, "INVALID_CATEGORY", "Unknown category")
        require(
            all(0 < len(p) <= 300 for p in body.phrases),
            "INVALID_PHRASE",
            "Each phrase must be 1–300 characters",
        )
        with db.transaction() as s:
            row = s.execute(
                select(Policy).where(Policy.id == "disclosure:" + category).with_for_update()
            ).scalar_one_or_none()
            version = db.decrypt(row.data)["version"] if row else 0
            require(body.version == version, "STALE_VERSION", "Refresh disclosure rules before editing")
            s.merge(
                Policy(
                    id="disclosure:" + category,
                    data=db.encrypt(
                        {"phrases": body.phrases, "version": version + 1, "approved_at": now().isoformat()}
                    ),
                )
            )
        return {"version": version + 1}

    @app.get("/v1/disclosures")
    def disclosures(device=Depends(owner)):
        with db.transaction() as s:
            return {
                "items": {
                    r.id.removeprefix("disclosure:"): db.decrypt(r.data)
                    for r in s.scalars(select(Policy).where(Policy.id.like("disclosure:%")))
                }
            }

    @app.post("/v1/assistant/interpret")
    def interpret(body: Interpret, device=Depends(owner)):
        # Narrow deterministic parser, with ephemeral input and no model/API charge.
        for prefix, kind in [("task:", "task"), ("note:", "note")]:
            if body.text.lower().startswith(prefix) and body.text[len(prefix) :].strip():
                return {
                    "type": kind,
                    "text": body.text[len(prefix) :].strip(),
                    "requires_local_confirmation": True,
                }
        return {
            "type": "clarification",
            "text": "Use 'task: …' or 'note: …'. Cloud conversation and multilingual speech are not connected.",
        }

    @app.post("/v1/calendar/mutation-proposals")
    def proposal(body: CalendarProposal, device=Depends(owner)):
        if settings.calendar_provider != "google":
            simulated()
        preview = (
            calendar.preview(body.model_dump())
            if isinstance(calendar, GoogleCalendar)
            else {"conflicts": "SIMULATED"}
        )
        with db.transaction() as s:
            result = save_intent(s, "calendar", body.model_dump(), device)
            return {**result, "simulation": not isinstance(calendar, GoogleCalendar), **preview}

    def apply_calendar(iid, device):
        failure = None
        with db.transaction() as s:
            row = s.execute(select(Intent).where(Intent.id == iid).with_for_update()).scalar_one_or_none()
            require(row is not None and row.kind == "calendar", "INVALID_INTENT", "Unknown proposal")
            data = db.decrypt(row.data)
            require(data["device"] == device, "WRONG_DEVICE", "Use the proposing device")
            if data["status"] == "COMPLETED":
                return data["result"]
            require(
                data["status"] == "APPROVED", "CONFIRMATION_REQUIRED", "Explicit owner confirmation required"
            )
            proposal = {k: data[k] for k in CalendarProposal.model_fields}
            try:
                result = calendar.write(s, proposal, iid)
                data.update(status="COMPLETED", result=result)
            except Problem as exc:
                failure = exc
                if exc.code in {
                    "CALENDAR_STALE",
                    "CALENDAR_REJECTED",
                    "CALENDAR_EXISTS",
                    "CALENDAR_FORBIDDEN",
                }:
                    data["status"] = "REJECTED"
            row.data = db.encrypt(data)
        if failure:
            raise failure
        return result

    @app.post("/v1/calendar/mutation-proposals/{iid}/confirm")
    def confirm_calendar(iid: str, body: Confirmation, device=Depends(owner)):
        if settings.calendar_provider != "google":
            simulated()
        # Persist exact owner authorization BEFORE crossing the external API boundary.
        with db.transaction() as s:
            row, data = confirm_intent(s, iid, "calendar", body.nonce, device)
            if data["status"] == "COMPLETED":
                return data["result"]
            data.update(status="APPROVED", approved_at=now().isoformat())
            row.data = db.encrypt(data)
        return apply_calendar(iid, device)

    @app.get("/v1/calendar/pending")
    def pending_calendar(device=Depends(owner)):
        with db.transaction() as s:
            result = []
            for row in s.scalars(select(Intent).where(Intent.kind == "calendar")):
                data = db.decrypt(row.data)
                if data["device"] == device and data["status"] == "APPROVED":
                    result.append(
                        {"id": row.id, "proposal": {k: data[k] for k in CalendarProposal.model_fields}}
                    )
            return {"items": result}

    @app.post("/v1/calendar/mutation-proposals/{iid}/reconcile")
    def reconcile_calendar(iid: str, device=Depends(owner)):
        if settings.calendar_provider != "google":
            simulated()
        return apply_calendar(iid, device)

    return app
