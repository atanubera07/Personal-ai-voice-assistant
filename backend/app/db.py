from contextlib import contextmanager

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import JSON, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "owner_device"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0)


class Call(Base):
    __tablename__ = "call_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_ref: Mapped[str] = mapped_column(String(100), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    private: Mapped[str] = mapped_column(Text, default="")
    deleted: Mapped[bool] = mapped_column(default=False)


class Event(Base):
    __tablename__ = "call_event"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(36), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))


class Budget(Base):
    __tablename__ = "budget_period"
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    limit: Mapped[int] = mapped_column(Integer, default=50000)
    confirmed: Mapped[int] = mapped_column(Integer, default=0)
    estimated: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)


class Intent(Base):
    __tablename__ = "owner_intent"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    data: Mapped[str] = mapped_column(Text)


class Outbox(Base):
    __tablename__ = "notification_outbox"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(30), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class Policy(Base):
    __tablename__ = "owner_policy"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    data: Mapped[str] = mapped_column(Text)


class Database:
    def __init__(self, settings):
        import json

        self.json = json
        self.encryption_keys = (settings.encryption_key, *settings.previous_encryption_keys)
        self.cipher = MultiFernet(
            [Fernet(key.encode()) for key in (settings.encryption_key, *settings.previous_encryption_keys)]
        )
        self.engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
            pool_pre_ping=True,
            hide_parameters=True,
        )
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def number_fingerprints(self, number):
        import hashlib
        import hmac

        return {
            hmac.new(key.encode(), ("contact:" + number).encode(), hashlib.sha256).hexdigest()
            for key in self.encryption_keys
        }

    def encrypt(self, value):
        return self.cipher.encrypt(self.json.dumps(value).encode()).decode()

    def decrypt(self, value):
        return self.json.loads(self.cipher.decrypt(value.encode())) if value else {}

    @contextmanager
    def transaction(self):
        with self.sessions() as session:
            # Serialize mutations across processes. Postgres row locks additionally protect budget/calls.
            if self.engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise


class Recording(Base):
    __tablename__ = "recording"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(30), default="RECORDING")
    expiry_at: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    receipt: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Pairing(Base):
    __tablename__ = "device_pairing"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[int] = mapped_column(Integer)
    used: Mapped[bool] = mapped_column(default=False)


class Challenge(Base):
    __tablename__ = "device_challenge"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    nonce: Mapped[str] = mapped_column(String(100))
    expires: Mapped[int] = mapped_column(Integer, index=True)
    used: Mapped[bool] = mapped_column(default=False)


class RequestNonce(Base):
    __tablename__ = "request_nonce"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[int] = mapped_column(Integer, index=True)


class RateBucket(Base):
    __tablename__ = "rate_bucket"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)
