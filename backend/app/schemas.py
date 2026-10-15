from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    device_id: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    secret: str = Field(min_length=32, max_length=200)


class ProviderEvent(Strict):
    event_id: str = Field(min_length=1, max_length=100)
    provider_call_id: str = Field(min_length=1, max_length=100)
    type: Literal[
        "received",
        "disclosed",
        "consent",
        "urgent",
        "media_ready",
        "recording_stopped",
        "bridge_confirmed",
        "ai_left",
        "handoff_failed",
        "ended",
        "connection_lost",
    ]
    processing: bool = False
    recording: bool = False
    summary: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=200)
    expected_version: int | None = Field(default=None, ge=0)
    reserve_paise: int = Field(default=1000, ge=1, le=50000)
    estimated_cost_paise: int = Field(default=0, ge=0)
    caller_number: str | None = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")


class Takeover(Strict):
    device_id: str
    idempotency_key: str = Field(min_length=8, max_length=100)


class Approval(Strict):
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount_paise: int = Field(gt=0, le=1000000)


class Confirmation(Strict):
    nonce: str = Field(min_length=20, max_length=200)


class Contact(Strict):
    number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    display_name: str = Field(min_length=1, max_length=100)
    category: Literal["Family", "Friends", "Work", "Unknown"]
    enabled: bool = True


class Disclosure(Strict):
    phrases: list[str] = Field(max_length=20)
    version: int = Field(ge=0)


class Interpret(Strict):
    text: str = Field(min_length=1, max_length=2000)
    locale: Literal["en-IN", "hi-IN", "bn-IN"] = "en-IN"


class CalendarProposal(Strict):
    operation: Literal["create", "edit", "delete"]
    calendar_id: str = Field(min_length=1, max_length=200)
    event_id: str | None = Field(default=None, max_length=200)
    source_etag: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    start: str
    end: str
    timezone: str
    attendees: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_times(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(self.timezone)
            start, end = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
            if not start.tzinfo or not end.tzinfo or end <= start:
                raise ValueError()
        except (ValueError, KeyError):
            raise ValueError(
                "Provide explicit start/end offsets, valid timezone and positive duration"
            ) from None
        if self.operation != "create" and (not self.event_id or not self.source_etag):
            raise ValueError("Edit/delete require event ID and current ETag")
        return self


class Enrollment(Strict):
    device_id: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    pairing_token: str = Field(min_length=32, max_length=100)
    public_key: str = Field(min_length=80, max_length=300)
    signature: str = Field(min_length=40, max_length=200)


class DeviceChallenge(Strict):
    device_id: str = Field(min_length=8, max_length=100)


class DeviceSession(DeviceChallenge):
    challenge_id: str = Field(min_length=36, max_length=36)
    signature: str = Field(min_length=40, max_length=200)
