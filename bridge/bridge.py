"""
RuView → Backend bridge
=======================

Subscribes to RuView's WebSocket. Detects fall events. Builds a webhook
payload with the surrounding context window and POSTs to the FastAPI
backend. Heartbeats the backend on a fixed interval.

Run
---
    cd bridge
    pip install -r requirements.txt
    cp .env.example .env
    # Edit .env — set BRIDGE_TOKEN (must match backend/.env) and HOME_ID
    python bridge.py

Designed to keep running through transient disconnects: WebSocket drops
trigger reconnect with exponential backoff; backend POST failures are
logged but don't crash the bridge.

What this does NOT do yet (deferred per plan)
---------------------------------------------
- Post-event confirmation filter (Phase 1, Tier 1). Right now every fall
  flag is forwarded immediately. The Phase-1 logic would wait 30s after
  the trigger, check that presence stayed in the room and motion dropped,
  and only then forward — auto-suppressing the bulk of false positives.
  TODO marker in the code below.
- Cross-node corroboration (Phase 1).
- Local SQLite buffer for events when backend is unreachable (Phase 2).
- Raw CSI capture when home.consent_csi_capture is true (Phase 2).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import websockets
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

RUVIEW_WS_URL = os.getenv("RUVIEW_WS_URL", "ws://localhost:3001/ws/sensing")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")
HOME_ID = int(os.getenv("HOME_ID", "1"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
PRE_EVENT_WINDOW_SEC = int(os.getenv("PRE_EVENT_WINDOW_SEC", "5"))
POST_EVENT_WINDOW_SEC = int(os.getenv("POST_EVENT_WINDOW_SEC", "30"))

# RuView ticks roughly at 10 Hz, so 5 sec ≈ 50 entries. Pad the deque.
HISTORY_MAXLEN = PRE_EVENT_WINDOW_SEC * 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bridge")


# ---------------------------------------------------------------------------
# Fall detection — matches several possible RuView field conventions
# ---------------------------------------------------------------------------
# The live WebSocket "sensing_update" frame (see samples/vitals-packet.json)
# carries the motion state as a STRING in classification.motion_level (e.g.
# "present_still") — NOT a boolean fall flag. So we check that first. We keep
# the boolean / numeric / flags / events conventions too, in case a different
# RuView build exposes the fall that way. The exact live token for a real fall
# is confirmed by running scripts/ruview_explorer.py against a triggered fall.
FALL_TOKENS = ("fall", "fallen", "falling", "collapse")


def _looks_like_fall_label(value: Any) -> bool:
    return isinstance(value, str) and any(tok in value.lower() for tok in FALL_TOKENS)


def _truthy_flag(value: Any) -> bool:
    """A fall flag may arrive as True, or as the float/int 1.0 (RuView encodes
    it as 0.0 / 1.0). Note `1.0 is True` is False in Python, so test value."""
    if value is True:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value >= 0.5
    return False


def detect_fall(msg: dict) -> tuple[bool, Optional[str], Optional[float]]:
    """Return (is_fall, which_field, confidence)."""
    if not isinstance(msg, dict):
        return (False, None, None)

    classification = msg.get("classification")
    if not isinstance(classification, dict):
        classification = {}
    conf = msg.get("confidence") or msg.get("conf") or classification.get("confidence")

    # 1. String motion state — the shape we actually observed in the live frame.
    for container, key in (
        (msg, "motion_level"), (classification, "motion_level"),
        (msg, "state"), (classification, "state"),
        (msg, "activity"), (classification, "activity"),
    ):
        val = container.get(key) if isinstance(container, dict) else None
        if _looks_like_fall_label(val):
            return (True, f"{key}={val}", conf)

    # 2. Boolean / numeric (0.0|1.0) fall flags.
    for field in ("fall", "fall_flag", "is_fall", "fall_detected"):
        if _truthy_flag(msg.get(field)):
            return (True, field, conf)
        if _truthy_flag(classification.get(field)):
            return (True, f"classification.{field}", conf)

    # 3. String event type (a normal frame's top-level type is "sensing_update").
    et = msg.get("event_type") or msg.get("type") or msg.get("event")
    if isinstance(et, str) and "fall" in et.lower():
        return (True, f"event_type={et}", conf)

    # 4. Bit-packed flags — bit 1 = fall (per ADR-018).
    flags = msg.get("flags")
    if isinstance(flags, int) and (flags & 0b10):
        return (True, f"flags bit 1 (raw={flags:b})", conf)

    # 5. Nested events array.
    events = msg.get("events")
    if isinstance(events, list):
        for ev in events:
            if isinstance(ev, dict):
                is_fall, which, ev_conf = detect_fall(ev)
                if is_fall:
                    return (True, f"events[].{which}", ev_conf or conf)

    return (False, None, None)


def extract_node_id(msg: dict) -> Optional[str]:
    # Explicit top-level node identifiers first.
    for field in ("node_id", "node", "mac", "device_id"):
        if field in msg:
            return str(msg[field])
    # The live frame nests sensors under a "nodes" list.
    nodes = msg.get("nodes")
    if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict):
        for field in ("node_id", "node", "mac", "id"):
            if field in nodes[0]:
                return str(nodes[0][field])
    # Last resort: a "source" label (e.g. "simulated").
    if "source" in msg:
        return str(msg["source"])
    return None


def compact_frame(msg: dict) -> dict:
    """Strip a sensing_update frame to the fields worth storing per event.

    Drops the bulky signal_field grid, raw subcarrier amplitudes, and per-person
    keypoint arrays; keeps classification, vitals, features, occupancy, and per-
    node RSSI. Keeps payloads ~0.5 KB instead of tens of KB so the webhook body
    and the DB JSON columns stay small.
    """
    if not isinstance(msg, dict):
        return {"raw": msg}
    out: dict = {}
    for key in ("type", "timestamp", "tick", "source",
                "classification", "features", "vital_signs", "estimated_persons"):
        if key in msg:
            out[key] = msg[key]
    nodes = msg.get("nodes")
    if isinstance(nodes, list):
        out["nodes"] = [
            {k: n.get(k) for k in ("node_id", "rssi_dbm", "subcarrier_count") if k in n}
            for n in nodes if isinstance(n, dict)
        ]
    persons = msg.get("persons")
    if isinstance(persons, list):
        out["persons"] = [
            {k: p.get(k) for k in ("id", "confidence", "zone") if k in p}
            for p in persons if isinstance(p, dict)
        ]
    return out


def _compact_window(entries: list) -> list:
    """Compact each {received_at, data} entry in a pre/post-event window."""
    return [
        {"received_at": e.get("received_at"), "data": compact_frame(e.get("data"))}
        for e in entries if isinstance(e, dict)
    ]


# ---------------------------------------------------------------------------
# Backend client
# ---------------------------------------------------------------------------
class BackendClient:
    def __init__(self, base: str, token: str):
        self.base = base
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = httpx.AsyncClient(timeout=10.0)

    async def post_fall(
        self,
        *,
        home_id: int,
        node_id: Optional[str],
        detected_at: datetime,
        confidence: Optional[float],
        vitals: dict,
        pre_window: list,
        post_window: list,
    ) -> None:
        body = {
            "home_id": home_id,
            "node_id": node_id,
            "event_type": "fall",
            "detected_at": detected_at.isoformat(),
            "confidence": confidence,
            "vitals_snapshot": vitals,
            "pre_event_window": pre_window,
            "post_event_window": post_window,
        }
        try:
            r = await self.client.post(f"{self.base}/webhook/fall-event",
                                       headers=self.headers, json=body)
            if r.status_code >= 300:
                log.error("backend rejected webhook: %d %s", r.status_code, r.text)
            else:
                log.info("backend stored event: %s", r.json())
        except httpx.HTTPError as e:
            log.error("backend unreachable: %s", e)

    async def heartbeat(self, home_id: int) -> None:
        try:
            r = await self.client.post(f"{self.base}/bridge/heartbeat",
                                       headers=self.headers, json={"home_id": home_id})
            if r.status_code >= 300:
                log.warning("heartbeat rejected: %d %s", r.status_code, r.text)
        except httpx.HTTPError as e:
            log.warning("heartbeat unreachable: %s", e)

    async def close(self):
        await self.client.aclose()


# ---------------------------------------------------------------------------
# Heartbeat task
# ---------------------------------------------------------------------------
async def heartbeat_loop(client: BackendClient) -> None:
    while True:
        await client.heartbeat(HOME_ID)
        await asyncio.sleep(HEARTBEAT_INTERVAL)


# ---------------------------------------------------------------------------
# Main event loop
# ---------------------------------------------------------------------------
async def consume_ws(client: BackendClient) -> None:
    backoff = 1.0
    while True:
        try:
            log.info("connecting to %s", RUVIEW_WS_URL)
            async with websockets.connect(RUVIEW_WS_URL) as ws:
                log.info("connected — listening for events (home_id=%d)", HOME_ID)
                backoff = 1.0  # reset on successful connect

                history: deque = deque(maxlen=HISTORY_MAXLEN)
                post_event_until: Optional[float] = None
                post_buffer: list = []
                pending_send: Optional[dict] = None

                async for raw in ws:
                    now = time.time()

                    if isinstance(raw, bytes):
                        log.debug("ignoring binary frame (%d bytes)", len(raw))
                        continue
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        log.debug("non-json frame: %r", raw[:80])
                        continue

                    entry = {"received_at": now, "data": msg}
                    history.append(entry)

                    # If we are inside a post-event capture window, accumulate
                    if post_event_until is not None:
                        post_buffer.append(entry)
                        if now >= post_event_until and pending_send is not None:
                            # Window complete — send
                            # TODO Phase 1 / Tier 1: insert post-event confirmation here.
                            # Check the post_buffer:
                            #   - did presence stay in the room?
                            #   - did motion drop to near-zero?
                            # If person stood up immediately, skip the send and
                            # log this as an auto-suppressed false alarm (still
                            # POST it with label_source="post_event_filter" so
                            # the model can learn from it later).
                            await client.post_fall(
                                home_id=HOME_ID,
                                node_id=pending_send["node_id"],
                                detected_at=pending_send["detected_at"],
                                confidence=pending_send["confidence"],
                                vitals=pending_send["vitals"],
                                pre_window=pending_send["pre_window"],
                                post_window=_compact_window(post_buffer),
                            )
                            post_event_until = None
                            post_buffer = []
                            pending_send = None
                        continue  # don't re-trigger inside the same window

                    # Otherwise, look for a new fall event
                    is_fall, which, confidence = detect_fall(msg)
                    if is_fall:
                        log.warning("FALL DETECTED via %s (conf=%s) — capturing window", which, confidence)
                        pending_send = {
                            "node_id": extract_node_id(msg),
                            "detected_at": datetime.now(timezone.utc),
                            "confidence": confidence,
                            "vitals": compact_frame(msg),
                            "pre_window": _compact_window(list(history)[:-1]),  # exclude the trigger frame
                        }
                        post_event_until = now + POST_EVENT_WINDOW_SEC
                        post_buffer = []

        except websockets.exceptions.ConnectionClosed as e:
            log.warning("ws closed: %s — reconnecting in %.1fs", e, backoff)
        except (ConnectionRefusedError, OSError) as e:
            log.warning("ws connect failed: %s — retrying in %.1fs", e, backoff)
        except Exception as e:
            log.exception("unexpected error: %s — retrying in %.1fs", e, backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)


async def main() -> None:
    if not BRIDGE_TOKEN:
        log.warning("BRIDGE_TOKEN is empty — backend will reject requests if it has one set")

    client = BackendClient(BACKEND_URL, BRIDGE_TOKEN)
    try:
        await asyncio.gather(
            consume_ws(client),
            heartbeat_loop(client),
        )
    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("interrupted, shutting down")
