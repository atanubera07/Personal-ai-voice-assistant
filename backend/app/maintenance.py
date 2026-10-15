"""Run hourly with backend environment: python -m app.maintenance --recording-root PATH."""

import argparse
import json

from .config import Settings
from .db import Database
from .recordings import RecordingStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recording-root", required=True)
    args = parser.parse_args()
    result = RecordingStore(Database(Settings.from_env()), args.recording_root).expire()
    print(json.dumps(result))
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
