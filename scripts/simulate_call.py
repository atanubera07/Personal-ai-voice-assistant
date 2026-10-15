"""Send signed synthetic events; never places a telephone call."""
import hashlib
import hmac
import json
import os
import time
import uuid
import urllib.request

base = os.environ.get("API_URL", "http://127.0.0.1:8000")
ref = "simulation-" + str(uuid.uuid4())
for kind, fields in [
    ("received", {}), ("disclosed", {}), ("consent", {"processing": True, "recording": False}),
    ("urgent", {"reason": "Synthetic test: callback requested"}),
    ("ended", {"summary": "Simulation: caller requested a callback.", "estimated_cost_paise": 750}),
]:
    body = json.dumps({"event_id": str(uuid.uuid4()), "provider_call_id": ref, "type": kind, **fields}).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(os.environ["WEBHOOK_SECRET"].encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(base + "/v1/provider/calls/events", data=body,
                                    headers={"Content-Type": "application/json", "X-Timestamp": timestamp, "X-Signature": signature})
    with urllib.request.urlopen(request) as response:
        result = json.load(response)
    print(kind, result["call_id"])
