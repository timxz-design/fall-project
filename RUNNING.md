# Running the full stack locally

End-to-end chain on your laptop, no hardware required.

```
RuView (Docker, simulator)  →  Bridge (Python)  →  Backend (FastAPI, SQLite)
        ws://localhost:3001          httpx POST              SQLite + FCM stub
```

## One-time setup

Open three PowerShell windows. In each, `cd "C:\Users\nikni\Desktop\fall detect"`.

### 1. Generate a shared bridge token

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output. It's the same value in `backend/.env` and `bridge/.env`.

### 2. Configure the backend

```powershell
cd backend
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Paste your token as `BRIDGE_TOKEN=...`. Save and close.

### 3. Configure the bridge

```powershell
cd ..\bridge
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Paste the *same* token as `BRIDGE_TOKEN=...`. Save and close.

## Start the stack

Three terminals, each runs one thing. Order matters: backend first, then
RuView, then bridge.

### Terminal 1 — backend

```powershell
cd "C:\Users\nikni\Desktop\fall detect\backend"
python app.py
```

You should see `backend ready — DB at sqlite:///./fall_detect.db`. Open
<http://localhost:8000/docs> in a browser to see the auto-generated API
docs. The `fall_detect.db` file will appear in the `backend/` folder on
first run.

### Terminal 2 — RuView

```powershell
docker run --rm -p 3000:3000 -p 3001:3001 -p 5005:5005/udp -e SENSING_BIND_ADDR=0.0.0.0 ruvnet/wifi-densepose:latest
```

Wait for `Data source: simulate` and `WebSocket server listening on 0.0.0.0:3001`.

### Terminal 3 — bridge

```powershell
cd "C:\Users\nikni\Desktop\fall detect\bridge"
python bridge.py
```

You should see `connected — listening for events (home_id=1)` followed by
periodic heartbeat lines.

## Create your test home

In a fourth terminal (or any HTTP client):

```powershell
curl -u admin:change-me -X POST http://localhost:8000/admin/homes `
  -H "Content-Type: application/json" `
  -d '{\"owner_name\":\"My test home\"}'
```

Response includes `id` and `install_code`. The `id` should be `1` if it's
your first home — which matches `HOME_ID=1` in `bridge/.env`. If it's
different, edit `bridge/.env` and restart the bridge.

Register a fake mobile device for that home (any string works as the
"FCM token" while we're using the stub):

```powershell
curl -X POST http://localhost:8000/register-device `
  -H "Content-Type: application/json" `
  -d '{\"install_code\":\"YOUR_CODE_HERE\",\"fcm_token\":\"FAKE_FOR_TEST\",\"platform\":\"ios\"}'
```

## Trigger a test fall

### Path A — through the bridge

If the RuView simulator emits fall events on its own (you'll know from the
bridge logs: `FALL DETECTED via ...`), the bridge will capture the
post-event window for 30s and then POST to the backend. Watch all three
terminal windows — you'll see:

- **Bridge:** "FALL DETECTED via ... — capturing window" → "backend stored event: ..."
- **Backend:** "[FCM stub] would send to FAKE_FOR_TEST..." → "event #1 stored"

### Path B — direct webhook (skips RuView)

If the simulator doesn't auto-fire falls, send a fake event directly to
the backend:

```powershell
curl -X POST http://localhost:8000/webhook/fall-event `
  -H "Authorization: Bearer YOUR_BRIDGE_TOKEN" `
  -H "Content-Type: application/json" `
  -d '{\"home_id\":1,\"event_type\":\"fall\",\"detected_at\":\"2026-05-16T10:00:00Z\",\"confidence\":0.84,\"vitals_snapshot\":{\"test\":true}}'
```

You should immediately see the backend log `[FCM stub] would send to FAKE_FOR_TEST...`.

## Label the event

```powershell
curl -X POST http://localhost:8000/events/1/label `
  -H "Content-Type: application/json" `
  -d '{\"label\":\"false_alarm\",\"note\":\"door slammed\"}'
```

## View the admin dashboard

Open <http://localhost:8000/admin/events> (basic auth: `admin` / `change-me`).
You'll see the event you just labeled, plus KPIs at the top.

## What this proves

Once you've seen `[FCM stub] would send to ...` log from a chain that
started in RuView's simulator, you've validated the entire architecture:

- RuView is producing data
- The bridge is parsing it correctly
- The backend is storing events with full context
- The fan-out to (would-be) push notifications works
- The label round-trip works
- The admin view aggregates correctly

Hardware just swaps the simulator for two real ESP32-S3 nodes. The bridge
and backend code don't change.

## Common issues

**Backend logs "Bridge call accepted with no BRIDGE_TOKEN configured".**
You left `BRIDGE_TOKEN` empty in `backend/.env`. Set it to a real value
and restart.

**Bridge logs "backend rejected webhook: 401".** The tokens don't match
between `bridge/.env` and `backend/.env`. Fix and restart both.

**Bridge logs "backend rejected webhook: 404 unknown home".** `HOME_ID`
in `bridge/.env` doesn't match an existing home in the backend. Create
the home via `POST /admin/homes` and update `HOME_ID`.

**Bridge logs "ws connect failed".** RuView container isn't running, or
ports aren't mapped correctly. Check `docker ps`.

**Heartbeats are silent in the backend log.** Heartbeat log level is
`DEBUG`, so they don't show by default. That's intentional — they'd be
noisy. Check `GET /status` to confirm the bridge is being seen.
