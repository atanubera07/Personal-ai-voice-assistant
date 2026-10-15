"""Operator-only commands. Run on the secured backend host, never expose through HTTP."""

import argparse

from sqlalchemy import select

from .config import Settings
from .db import Call, Database, Device, Intent, Policy
from .security import Auth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["pair", "revoke", "cleanup", "rotate-metadata"])
    parser.add_argument("--device-id")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    db = Database(settings)
    auth = Auth(db, settings)
    if args.command == "pair":
        print("One-use pairing token; expires in five minutes. Enter it only in your Android app:")
        print(auth.issue_pairing())
    elif args.command == "cleanup":
        auth.cleanup()
    elif args.command == "rotate-metadata":
        import hashlib
        import hmac

        with db.transaction() as session:
            for model, column in ((Call, "private"), (Policy, "data"), (Intent, "data")):
                for row in session.scalars(select(model).with_for_update()):
                    encrypted = getattr(row, column)
                    if not encrypted:
                        continue
                    value = db.decrypt(encrypted)
                    if model is Policy and row.id.startswith("contact:"):
                        value["fingerprint"] = hmac.new(
                            settings.encryption_key.encode(),
                            ("contact:" + value["number"]).encode(),
                            hashlib.sha256,
                        ).hexdigest()
                    setattr(row, column, db.encrypt(value))
        print(
            "Metadata re-encrypted. Retain old keys until recording files and retained backups are addressed."
        )
    else:
        if not args.device_id:
            parser.error("revoke requires --device-id")
        with db.transaction() as session:
            device = session.execute(
                select(Device).where(Device.id == args.device_id).with_for_update()
            ).scalar_one_or_none()
            if device:
                device.enabled = False
        print("Device revoked if it existed.")


if __name__ == "__main__":
    main()
