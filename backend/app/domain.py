from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone


def now():
    return datetime.now(timezone.utc)


class Problem(Exception):
    def __init__(self, code, detail, status=409):
        self.code, self.detail, self.status = code, detail, status


def require(condition, code, detail):
    if not condition:
        raise Problem(code, detail)


@dataclass
class CallState:
    phase: str = "DISCLOSURE"
    recording: str = "OFF"
    handoff: str = "NONE"
    processing: bool | None = None
    consent: bool | None = None
    urgent: bool = False
    version: int = 0
    ended_at: str | None = None
    expiry_at: str | None = None
    reserve: int = 0
    period: str = ""
    category: str = "Unknown"

    def apply(self, event, payload):
        require(
            self.phase not in {"ENDED", "FAILED_ROUTED"}
            and (self.phase != "UNKNOWN_TERMINAL" or event == "ended"),
            "CALL_ENDED",
            "Call is no longer active",
        )
        if event == "disclosed":
            require(self.phase == "DISCLOSURE", "INVALID_STATE", "Disclosure already resolved")
            self.phase = "CONSENT_RESOLUTION"
        elif event == "consent":
            require(self.phase == "CONSENT_RESOLUTION", "INVALID_STATE", "Disclosure must precede consent")
            self.processing, self.consent = payload["processing"], payload["recording"]
            if not self.processing:
                self.consent = False
                self.recording, self.phase = "NEVER_RECORDED", "TERMINATING"
            else:
                self.phase = "AI_ACTIVE"
                self.recording = "RECORDING" if self.consent else "NEVER_RECORDED"
        elif event == "urgent":
            require(self.phase == "AI_ACTIVE" and self.processing, "INVALID_STATE", "AI must be active")
            self.urgent = True
        elif event == "takeover":
            require(self.phase == "AI_ACTIVE", "INVALID_STATE", "AI must be active")
            self.phase, self.handoff = "TAKEOVER_PREP", "OWNER_AUTHENTICATED"
        elif event == "media_ready":
            require(self.handoff == "OWNER_AUTHENTICATED", "INVALID_STATE", "No pending owner leg")
            self.handoff = "OWNER_MEDIA_READY"
            if self.recording == "RECORDING":
                self.recording = "STOPPING"
        elif event == "recording_stopped":
            require(self.handoff == "OWNER_MEDIA_READY", "INVALID_STATE", "Owner media must be ready")
            if self.recording == "STOPPING":
                self.recording = "STOPPED"
            require(
                self.recording in {"STOPPED", "NEVER_RECORDED", "OFF"},
                "RECORDING_ACTIVE",
                "Recording stop has not been acknowledged",
            )
            self.handoff = "RECORDING_STOP_ACK"
        elif event == "bridge_confirmed":
            require(
                self.handoff == "RECORDING_STOP_ACK" and self.recording not in {"RECORDING", "STOPPING"},
                "RECORDING_ACTIVE",
                "Bridge blocked until recording stop acknowledgement",
            )
            self.phase, self.handoff = "OWNER_ACTIVE", "OWNER_CONNECTED"
        elif event == "ai_left":
            require(self.handoff == "OWNER_CONNECTED", "INVALID_STATE", "Two-way owner media not confirmed")
            self.handoff = "AI_LEFT"
        elif event == "handoff_failed":
            require(self.phase == "TAKEOVER_PREP", "INVALID_STATE", "No pending handoff")
            # A failure is NOT a stop acknowledgement. Stay blocked if the recorder may still be on.
            require(
                self.recording not in {"RECORDING", "STOPPING"}, "STOP_UNCONFIRMED", "Stop recorder first"
            )
            self.phase, self.handoff = "AI_ACTIVE", "AI_CONTINUES_UNRECORDED"
        elif event == "ended":
            self.phase = "ENDED"
            self.ended_at = now().isoformat()
            if self.consent:
                self.recording = "STOPPED"
                self.expiry_at = (datetime.fromisoformat(self.ended_at) + timedelta(days=30)).isoformat()
        elif event == "connection_lost":
            self.phase = "UNKNOWN_TERMINAL"
            # No trusted end timestamp, no release of reservations, no invented zero charge.
        else:
            raise Problem("UNKNOWN_EVENT", "Unsupported provider event", 422)
        self.version += 1
        return asdict(self)


CALLER_TOOLS = frozenset(
    {
        "take_message",
        "classify_urgency",
        "request_repetition",
        "close_conversation",
        "request_owner_handoff",
        "approved_disclosure",
    }
)


def caller_tool_allowed(name):
    return name in CALLER_TOOLS
