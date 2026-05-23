"""
Fall Detection Backend — MVP scaffold
======================================

A single-file FastAPI service for the Day 3 work in mvp-plan-v2.md.

Endpoints
---------
- POST /webhook/fall-event     — receives events from the bridge service
- POST /bridge/heartbeat       — bridge pings here every 30s
- POST /register-device        — mobile app registers FCM token w/ install code
- POST /events/{id}/label      — family member labels an event in one tap
- GET  /events                 — paginated event history for a home
- GET  /status                 — overall health snapshot
- GET  /admin/events           — simple HTML view of recent events
- POST /admin/homes            — create a home, returns install code

Run
---
    cd backend
    pip install -r requirements.txt
    cp .env.example .env
    # edit .env to set BRIDGE_TOKEN
    uvicorn app:app --reload --port 8000

What's NOT here yet (deliberately deferred per plan)
----------------------------------------------------
- Native Firebase Admin / direct APNs integration. Push now goes through the
  Expo push service (see notify_devices), which relays to APNs/FCM using the
  credentials in your EAS project. A direct firebase-admin path can be added
  later for App Store builds that move off Expo's relay.
- Postgres migration. Stay on SQLite until ~50 homes per plan.
- Bridge-side post-event confirmation filter (Phase 1 of roadmap).
- Per-home threshold storage and use (Phase 1).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import string
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import HTMLResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from pydantic import BaseModel, Field
from sqlmodel import Column, Field as SQLField, JSON, Session, SQLModel, create_engine, select


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fall_detect.db")
FIREBASE_CREDS = os.getenv("FIREBASE_CREDS")  # may be None
# Optional: an Expo access token strengthens push security (enforces that only
# your account can send to your app's tokens). Not required for dev — leave unset.
EXPO_ACCESS_TOKEN = os.getenv("EXPO_ACCESS_TOKEN")

if not BRIDGE_TOKEN:
    logging.warning(
        "BRIDGE_TOKEN is empty — bridge auth is disabled. Set this in .env "
        "before exposing the backend to anything."
    )

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fall-backend")


# ---------------------------------------------------------------------------
# Database models (SQLModel)
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Home(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    install_code: str = SQLField(unique=True, index=True)
    owner_name: str = ""
    threshold_overrides_json: Optional[str] = None
    consent_csi_capture: bool = False
    created_at: datetime = SQLField(default_factory=_utcnow)
    last_bridge_heartbeat_at: Optional[datetime] = None


class Device(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    fcm_token: str = SQLField(unique=True, index=True)
    home_id: int = SQLField(foreign_key="home.id", index=True)
    platform: str  # "ios" | "android"
    last_seen_at: datetime = SQLField(default_factory=_utcnow)


class Event(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    home_id: int = SQLField(foreign_key="home.id", index=True)
    node_id: Optional[str] = None
    event_type: str = "fall"
    detected_at: datetime
    received_at: datetime = SQLField(default_factory=_utcnow)
    confidence: Optional[float] = None
    # Snapshots stored as JSON blobs for flexibility while the RuView event
    # schema is still being discovered. Convert to typed columns later.
    vitals_snapshot: dict = SQLField(default_factory=dict, sa_column=Column(JSON))
    pre_event_window: list = SQLField(default_factory=list, sa_column=Column(JSON))
    post_event_window: list = SQLField(default_factory=list, sa_column=Column(JSON))
    notified_at: Optional[datetime] = None
    # Labeling: filled in by the mobile app
    label: Optional[str] = None  # "real_fall" | "false_alarm" | "test" | "unsure"
    label_source: Optional[str] = None  # "user" | "controlled_test" | "post_event_filter"
    labeled_at: Optional[datetime] = None
    note: Optional[str] = None


class HomeMetric(SQLModel, table=True):
    """One row per home per day. Read by the automation layer (Tier 1+)."""
    id: Optional[int] = SQLField(default=None, primary_key=True)
    home_id: int = SQLField(foreign_key="home.id", index=True)
    date: str  # ISO date 'YYYY-MM-DD'
    alerts_count: int = 0
    false_alarm_count: int = 0
    controlled_test_recall: Optional[float] = None
    baseline_drift_score: Optional[float] = None
    sensor_health_score: Optional[float] = None


engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def _init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Pydantic request/response schemas
# ---------------------------------------------------------------------------
class FallEventIn(BaseModel):
    home_id: int
    node_id: Optional[str] = None
    event_type: str = "fall"
    detected_at: datetime
    confidence: Optional[float] = None
    vitals_snapshot: dict = Field(default_factory=dict)
    pre_event_window: list = Field(default_factory=list)
    post_event_window: list = Field(default_factory=list)


class HeartbeatIn(BaseModel):
    home_id: int


class RegisterDeviceIn(BaseModel):
    install_code: str
    fcm_token: str
    platform: str  # "ios" | "android"


class LabelIn(BaseModel):
    label: str  # "real_fall" | "false_alarm" | "test" | "unsure"
    note: Optional[str] = None
    label_source: str = "user"


class CreateHomeIn(BaseModel):
    owner_name: str = ""
    consent_csi_capture: bool = False


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------
bearer = HTTPBearer(auto_error=False)
basic = HTTPBasic()


def require_bridge_token(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> None:
    if not BRIDGE_TOKEN:
        # In dev with no token configured, allow through but log loudly
        log.warning("Bridge call accepted with no BRIDGE_TOKEN configured")
        return
    if creds is None or not secrets.compare_digest(creds.credentials, BRIDGE_TOKEN):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad bridge token")


def require_admin(creds: HTTPBasicCredentials = Depends(basic)) -> None:
    user_ok = secrets.compare_digest(creds.username, ADMIN_USER)
    pass_ok = secrets.compare_digest(creds.password, ADMIN_PASS)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "bad admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


# ---------------------------------------------------------------------------
# Push notifications (Expo push service)
# ---------------------------------------------------------------------------
# The mobile app obtains an Expo push token (ExponentPushToken[...]) via
# expo-notifications and registers it here. We deliver alerts through Expo's
# push service, which relays to APNs (iOS) / FCM (Android) using the
# credentials configured in your EAS project. No Firebase SDK needed.
#
# Tokens that don't look like Expo tokens fall back to a log-only stub so the
# door stays open for a future native FCM/APNs path.
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"  # Expo push service endpoint


def _is_expo_token(token: str) -> bool:
    return token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken[")


def _send_expo_batch(messages: list[dict]) -> list[dict]:
    """POST a batch of push messages to Expo. Returns the per-message ticket
    list (each is {"status": "ok"|"error", ...}). Raises on transport failure."""
    payload = json.dumps(messages).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {EXPO_ACCESS_TOKEN}"
    req = urllib.request.Request(EXPO_PUSH_URL, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    data = body.get("data", [])
    # Expo returns a single object for a single message, a list for a batch.
    if isinstance(data, dict):
        data = [data]
    return data


def notify_devices(
    session: Session,
    devices: list["Device"],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> int:
    """Send a push to every device. Returns the number of accepted sends.

    Expo tokens are delivered via the Expo push service; any other token is
    logged only (no native FCM/APNs path wired yet). Tokens that Expo reports
    as DeviceNotRegistered are pruned so we stop trying dead installs.
    """
    expo_devices = [d for d in devices if _is_expo_token(d.fcm_token)]
    for d in devices:
        if not _is_expo_token(d.fcm_token):
            log.info(
                "[push stub] non-Expo token %s… — title=%r (no native FCM configured)",
                d.fcm_token[:12], title,
            )

    if not expo_devices:
        return 0

    messages = [
        {
            "to": d.fcm_token,
            "title": title,
            "body": body,
            "data": data or {},
            "sound": "default",
            "priority": "high",
            "channelId": "fall-alerts",  # matches the Android channel in the app
        }
        for d in expo_devices
    ]

    try:
        tickets = _send_expo_batch(messages)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log.error("[push] Expo push request failed: %s", exc)
        return 0

    sent = 0
    pruned = False
    for device, ticket in zip(expo_devices, tickets):
        if ticket.get("status") == "ok":
            sent += 1
            # The receipt id lets you confirm actual delivery later via Expo's
            # getReceipts endpoint — handy if iOS accepts but silently drops.
            log.info("[push] accepted token=%s… receipt_id=%s",
                     device.fcm_token[:18], ticket.get("id"))
            continue
        err = (ticket.get("details") or {}).get("error")
        log.warning(
            "[push] send failed token=%s… status=%s error=%s msg=%s",
            device.fcm_token[:18], ticket.get("status"), err, ticket.get("message"),
        )
        if err == "DeviceNotRegistered":
            session.delete(device)
            pruned = True
    if pruned:
        session.commit()
    return sent


# ---------------------------------------------------------------------------
# App + lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    log.info("backend ready — DB at %s", DATABASE_URL)
    yield


app = FastAPI(title="Fall Detection Backend", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Routes — bridge / webhook
# ---------------------------------------------------------------------------
@app.post("/webhook/fall-event", dependencies=[Depends(require_bridge_token)])
def receive_fall_event(payload: FallEventIn, session: Session = Depends(get_session)) -> dict:
    home = session.get(Home, payload.home_id)
    if home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown home")

    event = Event(
        home_id=payload.home_id,
        node_id=payload.node_id,
        event_type=payload.event_type,
        detected_at=payload.detected_at,
        confidence=payload.confidence,
        vitals_snapshot=payload.vitals_snapshot,
        pre_event_window=payload.pre_event_window,
        post_event_window=payload.post_event_window,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Fan out a push to every device registered for this home.
    devices = session.exec(select(Device).where(Device.home_id == payload.home_id)).all()
    sent = notify_devices(
        session,
        devices,
        title="Fall detected",
        body=f"Possible fall at {home.owner_name or 'home'} — tap to confirm",
        data={"event_id": str(event.id)},
    )
    event.notified_at = _utcnow()
    session.add(event)
    session.commit()

    log.info(
        "event #%d stored — home=%d devices_registered=%d devices_notified=%d confidence=%s",
        event.id, payload.home_id, len(devices), sent, payload.confidence,
    )
    return {"event_id": event.id, "devices_notified": sent}


@app.post("/bridge/heartbeat", dependencies=[Depends(require_bridge_token)])
def bridge_heartbeat(payload: HeartbeatIn, session: Session = Depends(get_session)) -> dict:
    home = session.get(Home, payload.home_id)
    if home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown home")
    home.last_bridge_heartbeat_at = _utcnow()
    session.add(home)
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Routes — mobile app
# ---------------------------------------------------------------------------
@app.post("/register-device")
def register_device(payload: RegisterDeviceIn, session: Session = Depends(get_session)) -> dict:
    home = session.exec(select(Home).where(Home.install_code == payload.install_code)).first()
    if home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bad install code")

    # Upsert by FCM token
    device = session.exec(select(Device).where(Device.fcm_token == payload.fcm_token)).first()
    if device is None:
        device = Device(fcm_token=payload.fcm_token, home_id=home.id, platform=payload.platform)
    else:
        device.home_id = home.id
        device.platform = payload.platform
        device.last_seen_at = _utcnow()
    session.add(device)
    session.commit()
    log.info("device registered for home=%d platform=%s", home.id, payload.platform)
    return {"home_id": home.id, "owner_name": home.owner_name}


@app.post("/events/{event_id}/label")
def label_event(event_id: int, payload: LabelIn, session: Session = Depends(get_session)) -> dict:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    event.label = payload.label
    event.label_source = payload.label_source
    event.note = payload.note
    event.labeled_at = _utcnow()
    session.add(event)
    session.commit()
    log.info("event #%d labeled %r by %s", event_id, payload.label, payload.label_source)
    return {"ok": True, "event_id": event_id, "label": event.label}


@app.get("/events")
def list_events(
    home_id: int,
    limit: int = Query(50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.exec(
        select(Event)
        .where(Event.home_id == home_id)
        .order_by(Event.detected_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "detected_at": e.detected_at.isoformat(),
            "confidence": e.confidence,
            "label": e.label,
            "label_source": e.label_source,
            "labeled_at": e.labeled_at.isoformat() if e.labeled_at else None,
            "note": e.note,
        }
        for e in rows
    ]


# ---------------------------------------------------------------------------
# Routes — status
# ---------------------------------------------------------------------------
@app.get("/status")
def status_view(session: Session = Depends(get_session)) -> dict:
    homes = session.exec(select(Home)).all()
    now = _utcnow()
    return {
        "ok": True,
        "homes_total": len(homes),
        "homes": [
            {
                "id": h.id,
                "owner_name": h.owner_name,
                "last_bridge_heartbeat_at": (
                    h.last_bridge_heartbeat_at.isoformat() if h.last_bridge_heartbeat_at else None
                ),
                "bridge_silent_seconds": (
                    int((now - h.last_bridge_heartbeat_at).total_seconds())
                    if h.last_bridge_heartbeat_at else None
                ),
            }
            for h in homes
        ],
    }


# ---------------------------------------------------------------------------
# Routes — admin
# ---------------------------------------------------------------------------
def _gen_install_code(n: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    # Avoid confusing chars
    alphabet = alphabet.replace("0", "").replace("O", "").replace("1", "").replace("I", "")
    return "".join(secrets.choice(alphabet) for _ in range(n))


@app.post("/admin/homes", dependencies=[Depends(require_admin)])
def create_home(payload: CreateHomeIn, session: Session = Depends(get_session)) -> dict:
    code = _gen_install_code()
    home = Home(install_code=code, owner_name=payload.owner_name,
                consent_csi_capture=payload.consent_csi_capture)
    session.add(home)
    session.commit()
    session.refresh(home)
    log.info("created home #%d install_code=%s", home.id, code)
    return {"id": home.id, "install_code": code, "owner_name": home.owner_name}


@app.get("/admin/events", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin_events_html(session: Session = Depends(get_session)) -> str:
    rows = session.exec(
        select(Event).order_by(Event.detected_at.desc()).limit(100)
    ).all()
    total = len(rows)
    labeled = sum(1 for e in rows if e.label is not None)
    real = sum(1 for e in rows if e.label == "real_fall")
    false_alarm = sum(1 for e in rows if e.label == "false_alarm")
    fp_rate = (false_alarm / labeled * 100) if labeled else 0.0

    rows_html = "".join(
        f"<tr>"
        f"<td>{e.id}</td>"
        f"<td>{e.home_id}</td>"
        f"<td>{e.detected_at.isoformat()}</td>"
        f"<td>{e.confidence if e.confidence is not None else '—'}</td>"
        f"<td>{e.label or '<i>unlabeled</i>'}</td>"
        f"<td>{e.note or ''}</td>"
        f"</tr>"
        for e in rows
    )

    return f"""<!doctype html>
<html><head><title>Fall Detection — Events</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #222; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 14px; }}
th {{ background: #f4f4f6; }}
.kpi {{ display: inline-block; margin-right: 2em; }}
.kpi b {{ font-size: 24px; display: block; }}
</style>
</head><body>
<h1>Recent Events (last 100)</h1>
<div class="kpi"><b>{total}</b>total</div>
<div class="kpi"><b>{labeled}</b>labeled</div>
<div class="kpi"><b>{real}</b>real falls</div>
<div class="kpi"><b>{false_alarm}</b>false alarms</div>
<div class="kpi"><b>{fp_rate:.1f}%</b>false-alarm rate (of labeled)</div>
<table>
  <thead><tr><th>id</th><th>home</th><th>detected_at</th><th>conf</th><th>label</th><th>note</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</body></html>"""


# ---------------------------------------------------------------------------
# Entry point for `python app.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    # Bind 0.0.0.0 so real devices on the LAN (e.g. your iPhone running the
    # dev build) can reach the API at http://<laptop-LAN-IP>:8000, not just
    # localhost. Keep behind your home firewall — this is for local testing.
    #
    # Pass the app object (not the "app:app" import string) and leave reload
    # off. Running `python app.py` imports this file as __main__ and defines
    # the SQLModel tables once; uvicorn's reloader would re-import it as `app`
    # and define the same tables again against the same metadata, crashing with
    # "Table 'home' is already defined". For auto-reload during backend dev,
    # run instead:  uvicorn app:app --reload --host 0.0.0.0 --port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
