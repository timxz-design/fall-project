# Day 1 Research Brief — Elderly Fall Detection MVP

_Date: 15 May 2026 — Author: Tim_

The week-plan assumed RuView would post a webhook to a cloud backend on a fall event. After reading the RuView docs, that's not quite how it works, and the architecture needs one small revision before Day 2. This brief answers each of the open questions in the plan, locks in the shopping list, and proposes the updated diagram.

---

## TL;DR

- **RuView does not push HTTP webhooks.** The sensing server broadcasts events over a WebSocket (`ws://<host>:3000/ws/sensing`). To get a webhook into FastAPI we add a tiny bridge process that subscribes to the WS and POSTs on fall events. ~30 lines of Python.
- **The sensing server must run on the customer's local network**, not on the Hetzner VPS. ESP32s send CSI over UDP/5005 and consumer routers won't forward inbound UDP from the internet. A Raspberry Pi 4 (or any €100 mini-PC) at the customer's home runs the RuView Docker image plus the bridge. The Hetzner VPS still hosts the FastAPI/FCM side.
- **Fall detection runs on-device** in the ESP32-S3 (Tier 2 DSP). The fall flag is bit 1 of the Flags field in the 32-byte vitals packet that the node emits at ~1 Hz. Server-side we read it from the WS stream.
- **Hardware:** ESP32-S3-DevKitC-1-N8R8 (8 MB flash / 8 MB PSRAM) is the right SKU. Order from Botland (PL) or TME (PL) for next-day EU delivery; Mouser EU has stock as a backup. ESP32 or ESP32-C3 are **not** supported — they're single-core.
- **Hetzner CX22** is fine (2 vCPU / 4 GB / 40 GB NVMe). Note the April 2026 price increase — it's closer to €4–8/mo now depending on region, still well under €10.
- **FCM HTTP v1** is the only path now; the legacy API was fully shut down in July 2024. Use `@react-native-firebase/messaging` on the app and Firebase Admin SDK on the backend.

---

## Revised Architecture

```
┌─────────── Customer's home ───────────┐      ┌──────── Hetzner VPS (EU) ────────┐
│                                       │      │                                  │
│  ESP32-S3 ──UDP/5005──┐                │      │   FastAPI (Python)               │
│  ESP32-S3 ──UDP/5005──┤                │      │     POST /webhook/fall-event ◄──┼── HTTPS
│                       ▼                │      │     POST /register-device       │
│              RuView sensing server     │      │     GET  /status                │
│              (Docker, on Pi 4 /        │      │                                  │
│               mini-PC)                 │      │   SQLite                         │
│                       │                │      │   Firebase Admin SDK ──FCM──► phone
│                       ▼ WebSocket      │      │                                  │
│              ruview-bridge.py ─────────┼──────►                                  │
│              (subscribes to WS,        │      │                                  │
│               watches fall flag,       │      │                                  │
│               POSTs to FastAPI)        │      │                                  │
└────────────────────────────────────────┘      └──────────────────────────────────┘
```

The bridge is the only new piece vs. the original plan. It's trivial to write — a single asyncio loop with `websockets` + `httpx` — but it gives you a clean local/cloud boundary, keeps the cloud webhook contract exactly as the plan describes, and lets you swap in a different sensing source later (e.g., a different vendor) without touching the backend.

---

## Open Questions From Day 1 — Answered

**1. Does the RuView sensing server emit a webhook on fall detection, or do you need to poll an API?**

Neither, exactly. The sensing server is a Rust Axum service that exposes both a REST API and a WebSocket at `ws://localhost:3000/ws/sensing` (or `:3001` if you prefer a dedicated WS port). Real-time events — including fall detection — are pushed over the WS as they happen. There is no built-in outbound HTTP webhook, so we add a small bridge process that translates WS → webhook.

**2. What's the exact event payload format for a fall event?**

Fall detection ships as part of the **32-byte binary vitals packet** the ESP32-S3 emits at 1 Hz (configurable). The packet starts with a magic number `0xC5110002` and contains: Node ID, Flags (bit 1 = fall), breathing BPM, heart rate BPM, RSSI, person count, motion energy, presence score, and a 4-byte timestamp at offset 24 (ms since boot). The sensing server decodes this and broadcasts a JSON form over the WebSocket. **Confirm exact JSON shape on Day 2** by running the Docker image with two simulated nodes and `wscat` against `/ws/sensing` — much faster than reading source.

**3. How sensitive is the default fall detection threshold — does it need calibration per home?**

The detector uses a **configurable phase-acceleration threshold**. The docs don't publish a "default = X" value, which is a soft signal that yes, you'll need to tune it per home. Day 6 in the plan is where that happens. Plan to start with whatever the firmware ships with, log every Tier 2 event for 24h, then tune.

**4. Can the sensing server run reliably on a small VPS, or does it need local compute?**

**Local compute, definitively.** Two reasons: (a) CSI flows from ESP32s over UDP/5005, and inbound UDP into a residential network from the internet is a non-starter — most ISPs are CGNAT'd, and even when they're not, the customer isn't going to configure port-forwarding; (b) the RuView Docker image itself is light (132 MB, Rust) but it's the *transport* that ties it to LAN. So: Pi 4 (€60–80) or any small x86 mini-PC at the customer site, running `docker run -p 3000:3000 -p 5005:5005/udp ruvnet/wifi-densepose:latest`.

Add **one more line item to the shopping list**: a Raspberry Pi 4 (4 GB) + power supply + microSD card per pilot home. ~€75 from Pi Hut / BerryBase / Welectron.

---

## Hardware Shopping List (Updated)

| Item | Qty | Unit | Source | Notes |
|------|-----|------|--------|-------|
| ESP32-S3-DevKitC-1-N8R8 | 2 | ~€11 | [Botland](https://botland.store/esp32-wifi-and-bt-modules/26547-esp32-s3-devkitc-1-n8r8-wifi-bluetooth-development-board-with-esp32-s3-wroom-1-chip.html) (PL) or [TME](https://www.tme.eu/) (PL) | Must be S3, with 8 MB PSRAM. ESP32 / C3 not supported. |
| USB-C cable + 5 V/2 A adapter | 2 | ~€8 | Any | For powering each node |
| Raspberry Pi 4 (4 GB) + 32 GB SD + PSU | 1 | ~€75 | [BerryBase](https://www.berrybase.de/) (DE) / Pi Hut | Runs RuView sensing server + bridge |
| Small project boxes (optional) | 2 | ~€4 | Any | Cosmetic; skip for first pilot |
| **Per-home total** | | **~€115** | | Within the spirit of the original "<€40" budget — the Pi is the extra |

Cloud:
- **Hetzner CX22** (EU Falkenstein or Helsinki) — 2 vCPU AMD / 4 GB / 40 GB NVMe / 20 TB traffic. €4–8/mo depending on region after the April 2026 adjustment. EU data residency, fine for GDPR.

---

## Stack Decisions Locked In For Day 2+

| Component | Choice | Why |
|-----------|--------|-----|
| Sensing firmware | RuView (Tier 0–2 on ESP32-S3) | Fall detection already implemented on-device |
| Local bridge | Python 3.12 + `websockets` + `httpx` | ~30 LOC; same language as backend |
| Backend | FastAPI + SQLite + Firebase Admin SDK | Matches your background |
| Hosting | Hetzner CX22 | EU, cheap, enough RAM |
| Mobile | React Native + `@react-native-firebase/messaging` + `notifee` | JS-familiar; canonical FCM library |
| Push API | FCM HTTP v1 | Only supported API since July 2024 |
| Auth between bridge → backend | Shared bearer token in `.env` for MVP | Replace with per-home API key post-MVP |

---

## What I Changed vs. The Original Plan

1. **Added a local "ruview-bridge" component** between the sensing server and the cloud backend. Tiny piece of code, but worth calling out so it gets a place in the repo on Day 3.
2. **Moved the sensing server to a Pi 4 at the customer site.** The original plan's footnote about local compute "if needed" — yes, it's needed. Architect for it from the start.
3. **Added Raspberry Pi 4 to the shopping list.** ~€75 extra per pilot home.
4. **Webhook payload is OUR shape, not RuView's.** Since we write the bridge, we get to define `POST /webhook/fall-event`'s body. Suggested:

   ```json
   {
     "home_id": "home_abc123",
     "node_id": 1,
     "event_type": "fall",
     "confidence": 0.87,
     "detected_at": "2026-05-15T14:32:11.244Z",
     "raw": { /* the decoded vitals packet, for debugging */ }
   }
   ```

5. **Confirmed React Native** is fine — `@react-native-firebase/messaging` is mature and handles foreground/background/killed states cleanly.

---

## Day 2 Plan (Adjusted)

Original Day 2 was "flash and provision ESP32 nodes." Same plan, but with two specific additions:

- Order the Pi 4 along with the ESP32s. Don't wait.
- While hardware is in transit, run RuView in Docker on your laptop using the simulated CSI source, point `wscat` at `ws://localhost:3000/ws/sensing`, and **capture a sample fall-event JSON message**. That sample becomes your contract for the bridge and the FastAPI webhook on Day 3.

Sketch of Day 2 deliverable:
- Both ESP32s flashed and emitting CSI to the Pi.
- A `samples/fall-event.json` file in the repo, captured from the WS, that the backend can be developed against.
- Decision recorded on whether to use UDP/5005 directly or the WS abstraction (use the WS — same data, easier to consume).

---

## Risks I'd Add to The Plan

| Risk | New mitigation |
|------|----------------|
| RuView's WS event schema changes between versions | Pin the Docker tag (`ruvnet/wifi-densepose:<digest>`), don't use `:latest` |
| Pi at customer's home loses internet | Bridge should buffer last-N events in SQLite locally and retry on reconnect; out of scope for MVP but cheap to add Day 5 |
| Bridge crashes silently | Systemd unit on the Pi with `Restart=always`, plus a heartbeat ping from bridge → backend every 30s — `GET /status` already exists in your plan, just have it check freshness |

---

## Sources

- [ruvnet/RuView — GitHub](https://github.com/ruvnet/RuView)
- [RuView user guide](https://github.com/ruvnet/RuView/blob/main/docs/user-guide.md)
- [RuView ESP32 CSI node firmware](https://github.com/ruvnet/RuView/tree/main/firmware/esp32-csi-node)
- [RuView quick start (DeepWiki)](https://deepwiki.com/ruvnet/RuView/2-quick-start)
- [ADR-012 — ESP32 CSI sensor mesh](https://github.com/ruvnet/RuView/blob/main/docs/adr/ADR-012-esp32-csi-sensor-mesh.md)
- [CNX Software writeup on RuView](https://www.cnx-software.com/2026/03/26/ruview-project-leverages-esp32-nodes-for-presence-detection-pose-estimation-and-breathing-heart-rate-monitoring/)
- [Hetzner Cloud pricing 2026](https://costgoat.com/pricing/hetzner)
- [Hetzner April 2026 price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)
- [React Native Firebase — messaging](https://rnfirebase.io/messaging/usage)
- [FCM HTTP v1 migration guide](https://medium.com/@prajapatimukesh0111/implement-push-notifications-in-react-native-with-firebase-fcm-http-v1-and-node-js-6d76922f5585)
- [Botland — ESP32-S3-DevKitC-1-N8R8](https://botland.store/esp32-wifi-and-bt-modules/26547-esp32-s3-devkitc-1-n8r8-wifi-bluetooth-development-board-with-esp32-s3-wroom-1-chip.html)
- [Mouser — ESP32-S3-DevKitC-1-N8R8](https://www.mouser.com/ProductDetail/Espressif-Systems/ESP32-S3-DevKitC-1-N8R8?qs=7D1LtPJG0i2PiuUUKucutQ%3D%3D)
