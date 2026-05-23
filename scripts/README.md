# Day 2 — Exploring RuView without hardware

Goal: figure out the actual shape of RuView's WebSocket events so the bridge
service and FastAPI webhook on Day 3 can be written against captured data
instead of guessing.

## 0. Fastest path — mock RuView (no Docker, no hardware)

If you just want to test the whole pipeline (bridge → backend → phone push)
without RuView at all, run the mock server. It pretends to be RuView: it streams
the captured `samples/vitals-packet.json` frame ~1 Hz over the same WebSocket the
bridge expects, and injects a `fall` every ~45 seconds.

Three terminals:

```powershell
# 1. Mock RuView (stop the real RuView Docker first — it owns port 3001)
python scripts/mock_ruview.py

# 2. Backend
cd backend; python app.py

# 3. Bridge
cd bridge; python bridge.py
```

About 8 seconds after the bridge connects, the mock logs `injecting FALL`; ~30s
later (the bridge's post-event capture window) the backend sends the push and
your phone buzzes. Tune timing with `MOCK_FIRST_FALL` / `MOCK_FALL_INTERVAL`, or
pick a free port with `MOCK_PORT` (then match the bridge's `RUVIEW_WS_URL`).

This proves everything downstream of RuView works. The steps below are for when
you want to explore the *real* RuView output — e.g. to confirm the live fall
field name once you can trigger an actual fall.

## 1. Start RuView in simulation mode

You don't need any ESP32 hardware to do this. RuView ships with a simulated CSI
source that emits fake events you can develop against.

```bash
# Pull the image (one-time)
docker pull ruvnet/wifi-densepose:latest

# Run it — port 3000 is HTTP + WebSocket, 3001 is dedicated WS, 5005/udp is CSI
docker run --rm \
  -p 3000:3000 \
  -p 3001:3001 \
  -p 5005:5005/udp \
  ruvnet/wifi-densepose:latest --simulate
```

If `--simulate` isn't the right flag for the version you pulled, run the image
with `--help` to see the actual flag (it may be `--demo`, `--mock`, or an env
var like `RUVIEW_MODE=simulate`). The docs reference simulation mode but the
exact CLI may differ across releases.

## 2. Open the Observatory UI

In a browser: <http://localhost:3000>

The Observatory is RuView's built-in dashboard. The HUD badge should switch
from "DEMO" to "LIVE" once data is flowing. This is a sanity check that the
container is working before you start subscribing programmatically.

## 3. Subscribe to the WebSocket and capture events

In another terminal:

```bash
# One-time setup
pip install websockets

# Run the explorer (cwd doesn't matter; samples/ resolves relative to script)
python scripts/ruview_explorer.py
```

You should immediately see JSON messages streaming. Roughly every second a
new vitals snapshot arrives. The first one gets auto-saved to
`samples/vitals-packet.json` as your baseline reference.

## 4. Trigger a simulated fall

How to do this depends on what simulation mode exposes. Options to try in
order:

1. **Look in the Observatory UI** for a "trigger event" button or fall toggle
   under a developer/debug menu.
2. **Check `/help` on the WebSocket**: send `{"action": "help"}` or similar
   to `ws://localhost:3000/ws/sensing` to see if it has a command channel.
3. **POST to the REST API**: `curl -X POST http://localhost:3000/events/simulate -d '{"type":"fall"}'`
   — this is speculative, check the actual API docs at <http://localhost:3000/docs>
   if Axum is serving an OpenAPI page.
4. **Set the simulate-fall env var** at container start: some RuView versions
   support `RUVIEW_SIM_FALL_INTERVAL=30s` to emit a fall every 30 seconds.

When a fall fires, the explorer prints `[!!!] FALL DETECTED via ...` and
writes a full window (5 sec before + 30 sec after) into
`samples/fall-event-<unix_ts>.json`. That file is the contract for the bridge
and the backend on Day 3.

## 5. What to look for in the captured data

Open `samples/vitals-packet.json` and `samples/fall-event-<ts>.json` and
answer these specific questions — they decide how you write the bridge:

- **Field name for the fall flag.** Is it `fall`, `fall_flag`, `is_fall`,
  a bit in `flags`, or something inside an `events` array? The explorer
  script prints which field convention matched.
- **Confidence score.** Does the payload include a probability/confidence,
  or just a binary flag? (Affects whether you can filter low-confidence
  events out in the bridge.)
- **Node identification.** Which ESP32 detected it? Is there a `node_id`,
  `mac`, or `room` field?
- **Timestamp.** ISO 8601 string? Unix epoch? Milliseconds since boot?
  Convert to ISO 8601 in the bridge for downstream sanity.
- **What else is in the same packet.** Heart rate, breathing rate,
  presence, motion energy, occupancy count — confirm these are in every
  vitals packet (they should be, per the docs). This is how Phase 2 of the
  roadmap gets heart-rate/breathing features essentially for free.

## 6. Commit the samples to the repo

Once captured, the JSON files in `samples/` become test fixtures for every
later piece of code:

- The bridge service has unit tests that replay these against its parser.
- The FastAPI backend has integration tests that POST these payloads to
  `/webhook/fall-event` and assert the right behaviour.
- The mobile app's "test alert" feature can be wired to one of these as
  its canned demo payload.

## Troubleshooting

**Connection refused on port 3000.** Docker isn't running, the container
crashed, or the port is bound to a different host. Check `docker ps`.

**Container starts but no events come over the WebSocket.** Simulation
mode may need an explicit flag to start emitting. Try `docker logs <id>`
to see what the server thinks it's doing.

**Binary frames instead of JSON.** You may be subscribed to a raw CSI
channel rather than the higher-level events channel. RuView exposes both
`/ws/sensing` (events, JSON) and `/ws/csi` (raw frames, binary). Stay
on `/ws/sensing` for this exercise.

**The explorer script doesn't detect falls.** The fall flag is in a field
the script doesn't know about yet. The script prints every message, so
look at the raw output during a known fall trigger and update the
`detect_fall()` function with the correct field name. Then send the
updated script back to me and I'll bake it into the bridge.
