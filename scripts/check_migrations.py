"""Destructive schema check ONLY on a dedicated disposable test database."""
import os
import secrets
import subprocess
from pathlib import Path
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

url = os.environ["TEST_DATABASE_URL"]
if not url.startswith("postgresql+psycopg://") or not url.rsplit("/", 1)[-1].endswith("_test"):
    raise SystemExit("Requires an explicitly disposable PostgreSQL database ending _test")
engine = create_engine(url)
with engine.begin() as connection:
    connection.execute(text("DROP SCHEMA public CASCADE"))
    connection.execute(text("CREATE SCHEMA public"))
env = {**os.environ, "DATABASE_URL": url, "SIMULATION": "false", "PUBLIC_ORIGIN": "https://agent.example",
       "DATA_KEY": Fernet.generate_key().decode(), **{k: secrets.token_urlsafe(32) for k in ["OWNER_SECRET", "JWT_SECRET", "WEBHOOK_SECRET"]}}
for command in [["alembic", "upgrade", "head"], ["alembic", "check"], ["alembic", "downgrade", "base"], ["alembic", "upgrade", "head"]]:
    subprocess.run(command, cwd=Path(__file__).resolve().parents[1] / "backend", env=env, check=True)
print("PostgreSQL upgrade/schema/downgrade/re-upgrade checks passed.")
