import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    owner_secret: str
    jwt_secret: str
    encryption_key: str
    webhook_secret: str
    simulation: bool = False
    public_origin: str = ""
    auth_rate_limit: int = 20
    previous_encryption_keys: tuple[str, ...] = ()

    calendar_provider: str = "disabled"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_calendar_id: str = "primary"

    def validate(self):
        from urllib.parse import urlparse

        from cryptography.fernet import Fernet

        for key in (self.encryption_key, *self.previous_encryption_keys):
            Fernet(key.encode())
        if any(len(value) < 32 for value in (self.owner_secret, self.jwt_secret, self.webhook_secret)):
            raise RuntimeError("Secrets must contain at least 32 characters")
        if self.calendar_provider not in {"disabled", "google"}:
            raise RuntimeError("CALENDAR_PROVIDER must be disabled or google")
        if self.calendar_provider == "google" and not all(
            (
                self.google_client_id,
                self.google_client_secret,
                self.google_refresh_token,
                self.google_calendar_id,
            )
        ):
            raise RuntimeError("Google Calendar requires client ID, secret, refresh token and calendar ID")
        if not self.simulation:
            origin = urlparse(self.public_origin)
            if (
                origin.scheme != "https"
                or not origin.hostname
                or origin.username
                or origin.path not in ("", "/")
            ):
                raise RuntimeError(
                    "Production requires PUBLIC_ORIGIN=https://your-host (no path or credentials)"
                )
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise RuntimeError("Production requires PostgreSQL and explicit Alembic migrations")

    @classmethod
    def from_env(cls):
        names = ["OWNER_SECRET", "JWT_SECRET", "DATA_KEY", "WEBHOOK_SECRET"]
        values = {name: os.environ.get(name, "") for name in names}
        if any(len(v) < 32 for v in values.values()):
            raise RuntimeError(
                "Set OWNER_SECRET, JWT_SECRET, DATA_KEY and WEBHOOK_SECRET; see scripts/setup_dev.py"
            )
        return cls(
            os.environ.get("DATABASE_URL", "sqlite:///./agent.db"),
            values["OWNER_SECRET"],
            values["JWT_SECRET"],
            values["DATA_KEY"],
            values["WEBHOOK_SECRET"],
            os.environ.get("SIMULATION", "false").lower() == "true",
            os.environ.get("PUBLIC_ORIGIN", ""),
            20,
            tuple(filter(None, os.environ.get("PREVIOUS_DATA_KEYS", "").split(","))),
            os.environ.get("CALENDAR_PROVIDER", "disabled"),
            os.environ.get("GOOGLE_CLIENT_ID", ""),
            os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
            os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
        )
