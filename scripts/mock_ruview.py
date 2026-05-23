#!/usr/bin/env python3
"""
mock_ruview.py — a stand-in for RuView, for testing the whole chain with no
hardware and no RuView/Docker.
=========================================================================

Serves a WebSocket at ws://localhost:3001/ws/sensing (the same URL the bridge
defaults to), streams the captured baseline frame (samples/vitals-packet.json)
about once a second so it looks like a live sensor, and periodically injects a
"fall" frame so the bridge fires.

Point the bridge at this and you can watch the full pipeline end to end:

    mock_ruview.py  ──ws──>  bridge.py  ──HTTP──>  backend (app.py)  ──>  phone

No ESP32, no Docker, no need to have figured out RuView's real fall trigger yet.

Run
---
    pip install websockets        # already in bridge/requirements.txt
    python scripts/mock_ruview.py

Then, in two other terminals: start the backend (cd backend && python app.py)
and the bridge (cd bridge && python bridge.py). Roughly MOCK_FIRST_FALL seconds
after the bridge connects you'll see the mock log "injecting FALL", and ~30s
later (the bridge's post-event capture window) the backend sends the push and
your phone buzzes.

Config (env vars)
-----------------
    MOCK_HOST            default "localhost"
    MOCK_PORT            default 3001        (match the bridge's RUVIEW_WS_URL)
    MOCK_FALL_INTERVAL   default 45  seconds between injected falls (0 = never)
    MOCK_FIRST_FALL      default 8   seconds before the first injected fall
    MOCK_FALL_COUNT      default 0   stop after this many falls (0 = unlimited).
                                     Set to 1 for a single, non-spammy test fall.

Note: if RuView's own Docker container is running it already owns port 3001 —
stop it first, or set MOCK_PORT and the bridge's RUVIEW_WS_URL to a free port.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Missing dependency. Run: pip install websockets", file=sys.stderr)
    sys.exit(1)


HOST = os.getenv("MOCK_HOST", "localhost")
PORT = int(os.getenv("MOCK_PORT", "3001"))
FALL_INTERVAL = int(os.getenv("MOCK_FALL_INTERVAL", "45"))  # seconds; 0 disables
FIRST_FALL = int(os.getenv("MOCK_FIRST_FALL", "8"))         # seconds until first fall
FALL_COUNT = int(os.getenv("MOCK_FALL_COUNT", "0"))         # max falls to inject; 0 = unlimited
TICK_SECONDS = 1.0

SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLE_PATH = SCRIPT_DIR.parent / "samples" / "vitals-packet.json"


def load_baseline() -> dict:
    """Use the real captured frame if present; otherwise a minimal stand-in."""
    if SAMPLE_PATH.exists():
        try:
            return json.loads(SAMPLE_PATH.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[mock] could not read {SAMPLE_PATH}: {exc} — using minimal frame")
    return {
        "type": "sensing_update",
        "source": "mock",
        "nodes": [{"node_id": 1, "rssi_dbm": -40.0, "subcarrier_count": 56}],
        "classification": {"motion_level": "present_still", "presence": True, "confidence": 0.5},
        "vital_signs": {"breathing_rate_bpm": 14.0, "heart_rate_bpm": 70.0},
        "estimated_persons": 1,
    }


BASELINE = load_baseline()


def make_frame(tick: int, fall: bool) -> dict:
    """A copy of the baseline frame with a fresh timestamp/tick. When fall=True,
    set classification.motion_level to 'fall' (the field the bridge reads) plus a
    numeric fall flag, so any detector convention catches it."""
    frame = copy.deepcopy(BASELINE)
    frame["timestamp"] = time.time()
    frame["tick"] = tick
    frame["source"] = "mock"
    classification = frame.get("classification")
    if not isinstance(classification, dict):
        classification = {}
        frame["classification"] = classification
    if fall:
        classification["motion_level"] = "fall"
        classification["confidence"] = 0.95
        frame["fall_detected"] = 1.0  # belt-and-suspenders for other detector variants
    else:
        classification.setdefault("motion_level", "present_still")
        frame.pop("fall_detected", None)
    return frame


async def stream(websocket, *_) -> None:
    peer = getattr(websocket, "remote_address", "?")
    print(f"[mock] client connected: {peer}")
    tick = 0
    falls_sent = 0
    try:
        while True:
            tick += 1
            due = (
                FALL_INTERVAL > 0
                and tick >= FIRST_FALL
                and (tick - FIRST_FALL) % FALL_INTERVAL == 0
            )
            capped = FALL_COUNT > 0 and falls_sent >= FALL_COUNT
            is_fall = due and not capped
            if is_fall:
                falls_sent += 1
                suffix = f" ({falls_sent}/{FALL_COUNT})" if FALL_COUNT else ""
                print(f"[mock] >>> injecting FALL frame (tick {tick}){suffix}")
                if FALL_COUNT and falls_sent >= FALL_COUNT:
                    print("[mock] fall cap reached — streaming baseline only from here")
            await websocket.send(json.dumps(make_frame(tick, fall=is_fall)))
            await asyncio.sleep(TICK_SECONDS)
    except websockets.exceptions.ConnectionClosed:
        print(f"[mock] client disconnected: {peer}")


async def main() -> None:
    src = "captured sample" if SAMPLE_PATH.exists() else "built-in minimal frame"
    print(f"[mock] RuView mock serving ws://{HOST}:{PORT}/ws/sensing")
    cap = f"{FALL_COUNT} total" if FALL_COUNT else "unlimited"
    print(f"[mock] streaming {src} @ 1 Hz; first fall in {FIRST_FALL}s, "
          f"then every {FALL_INTERVAL}s ({cap})")
    print("[mock] start the backend and bridge, then watch your phone. Ctrl+C to stop.")
    async with websockets.serve(stream, HOST, PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[mock] stopped")
