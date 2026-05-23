#!/usr/bin/env python3
"""
ruview_explorer.py
==================

Subscribe to RuView's WebSocket, pretty-print every incoming event, and auto-
capture the window around any fall event into samples/fall-event-<ts>.json.

This is intended for Day 2 exploration: figure out the actual JSON shape of
RuView's events so you can write the bridge service and the FastAPI webhook
against a real, captured payload instead of guessing from docs.

Usage
-----
    pip install websockets
    python ruview_explorer.py
    # or with a custom URL:
    python ruview_explorer.py ws://localhost:3000/ws/sensing

What it does
------------
1. Connects to ws://localhost:3000/ws/sensing (override with arg 1).
2. Logs every message to stdout, formatted as JSON if parseable, raw otherwise.
3. Keeps a rolling 5-second history of recent vitals.
4. When it detects a fall (using several possible field-name conventions, since
   the exact shape is what we're trying to discover), it captures the 5 seconds
   before + 30 seconds after into samples/fall-event-<unix_ts>.json.
5. Also writes the first message it sees to samples/vitals-packet.json so you
   have a "baseline" reference of what idle vitals look like.

Why the field-name detection is fuzzy
-------------------------------------
The 32-byte binary vitals packet from the ESP32 has bit 1 of the Flags field
= fall. The sensing server decodes that to JSON, but the exact JSON property
name isn't documented anywhere I could find — could be `fall`, `fall_flag`,
`is_fall`, `flags.fall`, or part of an `events` array. The script tries all
of these and prints which one matched, so you know how to write your bridge.
"""
import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Missing dependency. Run: pip install websockets", file=sys.stderr)
    sys.exit(1)


WS_URL = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:3001/ws/sensing"

# Resolve samples/ relative to this script's parent (so it works regardless of cwd)
SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = SCRIPT_DIR.parent / "samples"
SAMPLES_DIR.mkdir(exist_ok=True)

# Rolling windows
PRE_EVENT_WINDOW_SEC = 5
POST_EVENT_WINDOW_SEC = 30
# RuView sends vitals at ~1 Hz, so 5 sec ~= 5 entries. Pad to be safe.
HISTORY_MAXLEN = PRE_EVENT_WINDOW_SEC * 4


def compact_summary(msg: dict) -> str:
    """Build a short one-line summary from a vitals message.

    The live frame nests the interesting values under classification,
    vital_signs, and nodes[0], so flatten those first. `state=` (motion_level)
    is listed first on purpose — it's the field most likely to change at the
    moment of a fall, so watching this column is how you discover the real
    fall token if detect_fall() below doesn't already catch it.
    """
    if not isinstance(msg, dict):
        return f"<{type(msg).__name__}>"

    # Flatten nested shape so the lookups below find values whether they're
    # top-level or under classification / vital_signs / nodes[0].
    flat = dict(msg)
    if isinstance(msg.get("classification"), dict):
        flat.update(msg["classification"])
    if isinstance(msg.get("vital_signs"), dict):
        flat.update(msg["vital_signs"])
    nodes = msg.get("nodes")
    if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict):
        if "rssi_dbm" in nodes[0]:
            flat.setdefault("rssi", nodes[0]["rssi_dbm"])
        if "node_id" in nodes[0]:
            flat.setdefault("node_id", nodes[0]["node_id"])

    parts: list[str] = []
    field_groups = [
        (("motion_level", "state", "activity"), "state"),
        (("presence", "present", "occupancy", "presence_state"), "p"),
        (("motion", "motion_energy", "motion_score", "motion_band_power"), "m"),
        (("heart_rate", "hr", "heart_rate_bpm", "heartrate"), "hr"),
        (("breathing_rate", "br", "breathing_rate_bpm", "breathing_bpm", "respiration"), "br"),
        (("confidence", "conf"), "c"),
        (("rssi",), "rssi"),
        (("node_id", "node"), "node"),
    ]
    for keys, label in field_groups:
        for k in keys:
            if k in flat:
                v = flat[k]
                if isinstance(v, float):
                    parts.append(f"{label}={v:.2f}")
                else:
                    parts.append(f"{label}={v}")
                break

    if not parts:
        # Fallback — show first 3 scalar keys
        for k, v in list(msg.items())[:3]:
            if isinstance(v, (int, float, str, bool)):
                parts.append(f"{k}={v}")

    return " ".join(parts) if parts else f"<keys: {list(msg.keys())[:5]}>"


FALL_TOKENS = ("fall", "fallen", "falling", "collapse")


def _looks_like_fall_label(value) -> bool:
    return isinstance(value, str) and any(t in value.lower() for t in FALL_TOKENS)


def _truthy_flag(value) -> bool:
    # A fall flag may be True or the float/int 1.0 — `1.0 is True` is False.
    if value is True:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value >= 0.5
    return False


def detect_fall(msg: dict) -> tuple[bool, str | None]:
    """Try several possible field conventions. Return (is_fall, which_field).

    The live frame carries motion state as a STRING in classification.motion_level
    (e.g. "present_still"), so check that first; keep the boolean / numeric /
    flags / events conventions as fallbacks. If a real fall uses a token we
    don't match, the per-second summary prints `state=` — read it during a known
    fall and add the token to FALL_TOKENS above.
    """
    if not isinstance(msg, dict):
        return (False, None)

    classification = msg.get("classification") if isinstance(msg.get("classification"), dict) else {}

    # String motion state — the shape we actually observed in the live frame.
    for container, key in ((msg, "motion_level"), (classification, "motion_level"),
                           (msg, "state"), (classification, "state"),
                           (msg, "activity"), (classification, "activity")):
        val = container.get(key) if isinstance(container, dict) else None
        if _looks_like_fall_label(val):
            return (True, f"{key}={val}")

    # Boolean / numeric (0.0|1.0) fall flags
    for field in ("fall", "fall_flag", "is_fall", "fall_detected"):
        if _truthy_flag(msg.get(field)):
            return (True, field)
        if _truthy_flag(classification.get(field)):
            return (True, f"classification.{field}")

    # String event type
    et = msg.get("event_type") or msg.get("type") or msg.get("event")
    if isinstance(et, str) and "fall" in et.lower():
        return (True, f"event_type={et}")

    # Bit-packed flags field — bit 1 = fall per ADR-018
    flags = msg.get("flags")
    if isinstance(flags, int) and (flags & 0b10):
        return (True, f"flags bit 1 (raw={flags:b})")

    # Nested under "events" array
    events = msg.get("events")
    if isinstance(events, list):
        for ev in events:
            if isinstance(ev, dict) and detect_fall(ev)[0]:
                return (True, "events[].fall")

    return (False, None)


async def main() -> None:
    print(f"[connect] {WS_URL}")
    try:
        async with websockets.connect(WS_URL) as ws:
            print("[connected] streaming events. Ctrl+C to stop.\n")

            history: deque = deque(maxlen=HISTORY_MAXLEN)
            post_event_until: float | None = None
            post_buffer: list = []
            baseline_saved = False
            msg_count = 0
            last_summary_at = 0.0
            start_time = time.time()

            async for raw in ws:
                now = time.time()
                msg_count += 1

                # Decode
                if isinstance(raw, bytes):
                    print(f"[binary {len(raw)}b] {raw[:32].hex()}{'...' if len(raw) > 32 else ''}")
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    print(f"[non-json] {raw[:200]}")
                    continue

                # Save first message as baseline and print it in full
                if not baseline_saved:
                    out = SAMPLES_DIR / "vitals-packet.json"
                    out.write_text(json.dumps(msg, indent=2))
                    print("[first message — full JSON]")
                    print(json.dumps(msg, indent=2))
                    print(f"\n[saved baseline] {out}")
                    print("\n[streaming — one summary line per second; full JSON on fall events]\n")
                    baseline_saved = True
                elif now - last_summary_at >= 1.0:
                    # Throttled one-line summary
                    elapsed = now - start_time
                    print(f"[t+{elapsed:5.1f}s #{msg_count:5d}] {compact_summary(msg)}")
                    last_summary_at = now

                # Rolling history
                entry = {"received_at": now, "data": msg}
                history.append(entry)

                # Fall detection
                is_fall, which = detect_fall(msg)
                if is_fall and post_event_until is None:
                    print(f"\n[!!!] FALL DETECTED via `{which}` — capturing {POST_EVENT_WINDOW_SEC}s window")
                    print(json.dumps(msg, indent=2))
                    print()
                    post_event_until = now + POST_EVENT_WINDOW_SEC
                    post_buffer = []

                # Accumulate post-event window
                if post_event_until is not None:
                    post_buffer.append(entry)
                    if now >= post_event_until:
                        ts = int(now)
                        out = SAMPLES_DIR / f"fall-event-{ts}.json"
                        out.write_text(json.dumps({
                            "captured_at_unix": ts,
                            "ws_url": WS_URL,
                            "trigger_field": which,
                            "pre_event": list(history)[: -len(post_buffer)],
                            "trigger_and_post": post_buffer,
                        }, indent=2))
                        print(f"\n[saved fall window] {out}\n")
                        post_event_until = None
                        post_buffer = []

    except websockets.exceptions.InvalidURI:
        print(f"[error] Bad URL: {WS_URL}", file=sys.stderr)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[disconnected] code={e.code} reason={e.reason}", file=sys.stderr)
    except ConnectionRefusedError:
        print(
            f"[error] Connection refused at {WS_URL}.\n"
            "Is RuView running? Try:\n"
            "  docker run --rm -p 8080:8080 -p 8765:8765 -p 5005:5005/udp \\\n"
            "    ruvnet/wifi-densepose:latest --source simulate --bind-addr 0.0.0.0\n",
            file=sys.stderr,
        )
    except KeyboardInterrupt:
        print("\n[interrupted]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[interrupted]")
