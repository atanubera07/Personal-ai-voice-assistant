"""Generate local secrets without printing them; refuses to overwrite existing configuration."""
import os
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
path = root / "backend/.env"
content = "DATABASE_URL=sqlite:///./agent.db\nSIMULATION=true\n" + "\n".join(
    f"{key}={Fernet.generate_key().decode() if key == 'DATA_KEY' else secrets.token_urlsafe(48)}"
    for key in ["OWNER_SECRET", "JWT_SECRET", "DATA_KEY", "WEBHOOK_SECRET"]
) + "\n"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(content)
print("Created backend/.env (0600). Simulation only. Keep this file private.")
