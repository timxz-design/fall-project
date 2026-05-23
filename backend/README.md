# Backend — Fall Detection MVP

Single-file FastAPI service. See module docstring in `app.py` for the
endpoint list.

## Setup

```powershell
cd backend
pip install -r requirements.txt
copy .env.example .env
# Edit .env — at minimum, set BRIDGE_TOKEN to a long random string.
# Generate one with:
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Run

```powershell
uvicorn app:app --reload --port 8000
# or just:
python app.py
```

On first run, `fall_detect.db` is created in the working directory.

API docs are auto-published at <http://localhost:8000/docs> (Swagger UI)
and <http://localhost:8000/redoc>.

## Quick smoke test

Create a home (admin auth: `admin` / `change-me` by default):

```powershell
curl -u admin:change-me -X POST http://localhost:8000/admin/homes `
  -H "Content-Type: application/json" `
  -d '{"owner_name":"Test home"}'
```

You'll get back an `install_code`. Note the `id`.

Register a fake device for that home:

```powershell
curl -X POST http://localhost:8000/register-device `
  -H "Content-Type: application/json" `
  -d '{"install_code":"ABC123","fcm_token":"FAKE_TOKEN_FOR_TESTING","platform":"ios"}'
```

Send a fake fall event from the "bridge" (use the BRIDGE_TOKEN from `.env`):

```powershell
curl -X POST http://localhost:8000/webhook/fall-event `
  -H "Authorization: Bearer YOUR_BRIDGE_TOKEN" `
  -H "Content-Type: application/json" `
  -d '{"home_id":1,"event_type":"fall","detected_at":"2026-05-16T10:00:00Z","confidence":0.84}'
```

Backend logs will show `[FCM stub] would send to FAKE_TOKEN_...` — that's the
push notification we *would* send once Firebase is wired up.

Label the event:

```powershell
curl -X POST http://localhost:8000/events/1/label `
  -H "Content-Type: application/json" `
  -d '{"label":"false_alarm","note":"door slammed"}'
```

View the admin dashboard at <http://localhost:8000/admin/events>
(basic auth: `admin` / `change-me`).

## Next steps (deferred, per plan)

1. **Wire up Firebase Admin SDK.** Replace the body of `send_fcm()` in
   `app.py` with `firebase_admin.messaging.send(...)`. Initialize the SDK
   on app startup using `FIREBASE_CREDS`.
2. **Add the `home_metrics` daily rollup job.** Currently the table exists
   but isn't populated. Add a daily task (cron or APScheduler) that
   computes per-home metrics from `Event` rows.
3. **Postgres migration.** Switch `DATABASE_URL` to a `postgresql://` URL
   once you have ~50 homes. SQLModel/SQLAlchemy handle this transparently.
