# Bridge — RuView → Backend

Subscribes to RuView's WebSocket, detects fall events, POSTs to the
backend's `/webhook/fall-event`. Heartbeats the backend every 30s.

## Setup

```powershell
cd bridge
pip install -r requirements.txt
copy .env.example .env
# Edit .env — set BRIDGE_TOKEN (same value as backend/.env) and HOME_ID
```

## Run

Three things need to be running at the same time, in three terminals:

1. **RuView** (Docker, simulator mode):
   ```powershell
   docker run --rm -p 3000:3000 -p 3001:3001 -p 5005:5005/udp -e SENSING_BIND_ADDR=0.0.0.0 ruvnet/wifi-densepose:latest
   ```

2. **Backend** (FastAPI):
   ```powershell
   cd backend
   python app.py
   ```

3. **Bridge**:
   ```powershell
   cd bridge
   python bridge.py
   ```

When all three are up you'll see the bridge log `connected — listening for
events`, and heartbeat logs every 30 seconds in the backend.

## Triggering a fall in the simulator

By default RuView's auto-detected simulator may or may not produce
synthetic falls on its own. To force one, check:

- The Observatory UI at <http://localhost:3000/ui/index.html> for a
  "trigger fall" button.
- `curl http://localhost:3000/api/v1/` to list REST routes — there may be
  a `/simulate/fall` endpoint.

When a fall fires, the bridge logs `FALL DETECTED via ...`, waits 30s
to capture the post-event window, then POSTs to the backend. The backend
now sends a real push via the Expo service (not the old FCM stub), so
you'll see it log `[push] accepted token=… receipt_id=…` for each
registered device and the phone will actually buzz.

> Note on the fall field: the live `sensing_update` frame carries motion
> state as a string in `classification.motion_level` (e.g. `present_still`),
> not a boolean flag. `detect_fall()` already matches any value containing
> "fall"; if a real triggered fall uses a different token, run
> `scripts/ruview_explorer.py` and watch the `state=` column to find it,
> then add it to `FALL_TOKENS` in both `bridge.py` and the explorer.

## Verifying end-to-end with no fall trigger

Even if you can't trigger a real simulated fall yet, you can verify the
chain by sending a fake event directly to the backend webhook:

```powershell
curl -X POST http://localhost:8000/webhook/fall-event `
  -H "Authorization: Bearer YOUR_BRIDGE_TOKEN" `
  -H "Content-Type: application/json" `
  -d '{"home_id":1,"event_type":"fall","detected_at":"2026-05-16T10:00:00Z","confidence":0.84,"vitals_snapshot":{"test":true}}'
```

That tests everything past RuView.
