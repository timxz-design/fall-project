# Elderly Fall Detection — MVP Plan v2

_Updated 15 May 2026. Supersedes the original 1-week plan._

## What changed vs. v1

Three big shifts from the original plan, all informed by the Day 1 research:

1. **Architecture**: RuView doesn't push webhooks — it broadcasts over WebSocket from a Pi running locally at the customer's home. The plan now includes a small Python "bridge" service on the Pi that subscribes to the WS and POSTs to your FastAPI backend. (Detailed in `day-1-research-brief.md`.)
2. **Data labeling is now a first-class concern, baked into the MVP from Day 3.** The reason: RuView's fall detector is a threshold-based signal-processing pipeline, not an ML model. To meaningfully improve false-positive rates beyond the default, you need labeled data — and the easiest time to start capturing labels is the moment the first family member receives the first alert. Capturing labels from day one is what builds the data flywheel that eventually becomes the only real moat in this category.
3. **An automation layer is sized and sequenced alongside the data work.** Per-home tuning is unsustainable past ~10 homes if a human is doing it. The plan now explicitly includes four tiers of self-monitoring and self-adapting infrastructure, from simple control loops (Tier 1, Phase 1) up to LLM-based operational agents (Tier 3, Phase 2/3) and federated learning (Tier 4, Phase 4+). See the new "Automation Layer" section below.

The 7-day MVP timeline does not slip. The new work is small additions to the backend schema, the mobile UI, and the testing protocol — all of which were already on the menu.

---

## Goal (Unchanged)

A working end-to-end demo where a fall detected by RuView on an ESP32 triggers a push notification on a family member's phone within 5 seconds, **and the family member can label the event "real fall / false alarm / test" with one tap.**

---

## Day-by-Day Plan (v2)

### Day 1 — Hardware + RuView setup ✅ DONE
Research complete. Hardware ordered. See `day-1-research-brief.md` and `hardware-sourcing.md`.

### Day 2 — Flash, provision, capture sample data
Same as v1, with one explicit deliverable added:

- Flash both ESP32-S3 nodes with RuView firmware
- Provision WiFi credentials, point at Pi's local IP
- Get RuView Docker running on the Pi (or laptop while waiting for the Pi)
- Test fall detection by simulating falls (dropped pillow, controlled forward drop onto a mat)
- **NEW: Capture two reference artifacts in the repo:**
  - `samples/vitals-packet.json` — what the WS emits at 1 Hz when nothing is happening
  - `samples/fall-event.json` — what it emits at the moment of a triggered fall
  - These become the contract for the bridge service and the FastAPI webhook on Day 3

### Day 3 — Backend API (with labeling endpoints baked in)
Build the FastAPI service. The endpoint list now includes label capture from the start:

- `POST /webhook/fall-event` — receives fall events from the bridge service (not RuView directly)
- `POST /register-device` — mobile app registers FCM token, links to a home_id
- `POST /events/{event_id}/label` — mobile app sends ground truth: `{"label": "real_fall" | "false_alarm" | "test" | "unsure", "note": "optional text"}`
- `GET /events?home_id=X&limit=50` — paginated event history with label status
- `GET /status` — heartbeat from the bridge + recent event count

**Database schema** (SQLite, with future migration to Postgres in mind):

```
events(
  id, home_id, node_id, event_type, detected_at,
  vitals_snapshot_json,  -- the full vitals packet at trigger time
  pre_event_window_json, -- last 5 seconds of vitals readings before the event
  post_event_window_json,-- next 30 seconds after the event
  notified_at, label, label_source, labeled_at, note
)

devices(
  fcm_token, home_id, platform, last_seen_at
)

homes(
  id, install_code, owner_name, threshold_overrides_json, consent_csi_capture
)
```

The `pre_event_window_json` and `post_event_window_json` columns are the cheap version of "training data capture." Storing 35 seconds of vitals readings (35 × ~32 bytes = ~1 KB per event) costs essentially nothing and gives you context for every labeled event — which is what a future model would train on.

**Also add a `home_metrics` table now**, even if it's only populated by a stub job. Schema: `home_id, date, alerts_count, false_alarm_count, controlled_test_recall, baseline_drift_score, sensor_health_score`. This table is what the entire automation layer (Tier 1 onward) reads from — building it later means a more painful migration. One row per home per day, append-only. Tiny.

**Consent flag on the home record:** `consent_csi_capture`. Off by default. When the customer opts in, the bridge ALSO captures raw CSI frames (~5 seconds around each fall trigger) and ships them to a separate object storage bucket (S3-compatible, e.g. Hetzner Storage Box). This is the foundation for eventual ML training. GDPR-relevant — see Risks section.

Push notification setup: Firebase project, FCM HTTP v1 (legacy API was shut down July 2024), APNs auth key generated in Apple Developer console, uploaded to Firebase. Send a test push successfully.

### Day 4 — Mobile app (React Native, label flow built in)
Three screens (per v1) **plus a label-capture flow integrated into the alert screen.**

**Screen 1: Login/setup** — enter install code, links phone to a home_id.

**Screen 2: Status / Active alert** — when an alert fires, the screen shows:
- Time and location of detected fall ("Living room — 14:32")
- Three big buttons: **Real fall** / **False alarm** / **Not sure**
- "Test alert" option for the system test feature

The label is sent to `POST /events/{event_id}/label` on tap. Don't make the family member type anything. One tap, done.

**Screen 3: History (last 7 days)** — list of past events. Tapping any past event lets the user re-label it. Unlabeled events have a yellow "Tap to label" indicator. This solves the problem of "alert came in while phone was off, family member dealt with it, now there's no label" — they can backfill it.

**Settings screen** (small, behind a gear icon):
- Toggle: "Help improve the system by sharing detailed sensor data" (= `consent_csi_capture`)
- Default: OFF. Clear language about what it captures and that it never includes camera or microphone (because it doesn't).
- Test alert button for verification

FCM handling: foreground, background, and killed states. `@react-native-firebase/messaging` + `notifee` is the canonical combo. Build for both iOS (TestFlight distribution to pilots) and Android.

### Day 5 — Integration
Wire everything together end-to-end:

- ESP32 simulated fall → RuView → WS → bridge → FastAPI → FCM → phone → label tap → backend stored
- **Test the full chain 20+ times** including the label round-trip
- Verify event records contain the pre/post-event vitals windows (the labeled training data foundation)
- Add file-based logging on the bridge and the backend (Sentry can wait)

**NEW:** Add a tiny "ops view" — a single page at `GET /admin/events.html` (basic auth, env-vared password) that shows: total alerts last 7 days, labels distribution (X real / Y false alarms / Z unlabeled), per-home false-positive rate, last-heartbeat age per home. This is the dashboard you'll stare at during Day 6 to know whether the system is working — and it's the manual prototype of what the automation layer (Phase 1 Tier 1) will turn into a running control loop. Build the dashboard now so the metric definitions are stable before automation reads from them.

### Day 6 — Real-world testing (with explicit labeling protocol)
Install hardware at one trusted person's home. Run for 24 hours. Two changes from v1:

- **Label every single alert.** This is the protocol: when an alert fires, the family member taps Real fall / False alarm / Not sure within an hour. If they miss it, they backfill from the history screen the next morning.
- **Track baseline false-positive rate.** At the end of 24 hours, compute: false-alarm count / total-alert count. If it's above ~30%, the system is annoying enough that you need to tune thresholds before extending the pilot. If it's below ~10%, you have something tolerable.

Do controlled fall tests (a fit adult, onto a mat, in different rooms) to also measure recall: did the system catch them? How many did it miss? This goes into the same labeled dataset as `real_fall` entries with `label_source: "controlled_test"`.

### Day 7 — Polish + buffer
- Fix top 3 issues from Day 6
- Confirm the labeling flow is intuitive — show it to one family member who hasn't seen it and watch them use it without instruction
- One-page instruction sheet for the family
- 30-second demo video

---

## Post-MVP Roadmap — Building the Data Flywheel

The MVP ends at Day 7 with a working system in one home. Everything below is what turns it from "demo" into "defensible product." The unifying theme: **labeled data accumulating in your database is the only thing competitors can't trivially clone.**

### Phase 1 — Tune & Expand (Month 1–2)
**Goal:** Get to 5 pilot homes with structured labeling.

- Per-home threshold tuning. Use the labeled data from each home's first week to find a threshold that catches ≥95% of controlled-test falls while keeping false-alarm rate under 1 per week per home.
- Bridge-side post-event confirmation: when RuView fires a fall flag, wait 30 seconds before notifying — check that presence stayed in the room and motion dropped to near-zero. If the person stood up immediately, suppress the alert and auto-label as `false_alarm` with `label_source: "post_event_filter"`. This is the single highest-leverage tactical change and should reduce false positives 5–10× on its own.
- Cross-node corroboration: if two ESP32s see the event within a 2-second window, confidence goes up; if only one does, raise the threshold.
- Ship as TestFlight beta + Android internal testing track.
- **Success metric: per-home false-alarm rate <1 per week, with zero missed controlled-test falls.**

### Phase 2 — Capture Quality Data at Scale (Month 2–4)
**Goal:** 20 pilot homes generating labeled data continuously.

- Migrate database from SQLite to Postgres on the same Hetzner box (~2 hours of work, do it before you have 50+ homes).
- Stand up a proper "labeling admin" view — currently the ops dashboard is read-only; add the ability to filter events by `unlabeled`, `disputed`, `controlled_test`, etc. and inspect the vitals window for each.
- Add second-tier labeling: when a family member labels something `false_alarm`, ask a follow-up: "What was happening? (door slammed / pet jumped / someone sat down hard / I don't know)". Multi-choice, optional. This is the kind of granular labeling that lets you build sub-classifiers later.
- For families who've opted in to `consent_csi_capture`, you're now also accumulating raw CSI windows around every event — both real and false alarms.
- **Success metric: 200+ labeled events across pilot homes, with at least 20 confirmed real-fall captures (mix of controlled tests + real incidents).**

### Phase 3 — Custom WASM Detector (Month 4–7)
**Goal:** Ship a Rust WASM module that runs on the Pi alongside RuView's default detector, refining its output using the post-event filtering you've been doing in Python.

- Port the post-event confirmation logic from the Python bridge into a Rust WASM module signed in an RVF container (RuView's modular sensing extension format).
- Run A/B: half your fleet on the default detector, half on the new module. Measure false-alarm rate difference.
- If the WASM version is materially better, roll it out to all homes via fleet update.
- **Success metric: WASM module measurably outperforms baseline on labeled data, in production.**

### Phase 4 — ML Classifier (Month 7–12)
**Goal:** Train a small CNN or transformer on the accumulated CSI windows and replace the threshold detector with an inference model.

Prerequisites: ~500 labeled positives, ~5000 labeled negatives, ideally distributed across at least 10 different homes (for generalization). If you don't have that, stay in Phase 3 and keep collecting.

- Off-board training: pull the consented CSI windows from object storage, train candidate architectures (start small — a 1D CNN over subcarrier × time is a sensible baseline before reaching for transformers).
- Validation: held-out homes the model has never seen. The model has to generalize to new physical environments, not just to events it's seen before.
- Deployment: quantize to int8 or smaller, ship as a new WASM module on the Pi (a small CNN runs fine on Pi 5 — you may not even need an NPU stick).
- Keep the threshold detector running in shadow mode for a month after deployment so you can compare predictions and catch regressions before they hurt customers.
- **Success metric: ML classifier reduces false-alarm rate by another 2× over the WASM filter while maintaining ≥95% recall on controlled tests.**

### Phase 5 — Data Flywheel as Moat (Month 12+)
This is no longer a development phase, it's an operational discipline:

- Every home that joins contributes labels. Every label improves the model. A better model means lower false alarms, which means higher retention, which means more homes, which means more labels.
- The moat is the labeled CSI dataset — which is private, hard to acquire ethically, and grows automatically with usage.
- At some point this dataset may also have research value (CSI fall datasets are scarce in academia). Optional partnerships with university labs become possible — usually in exchange for refinement of the model on more diverse data.

---

## Automation Layer — Self-Adapting & Self-Monitoring

The Phase 1–5 roadmap above is mostly about *what* gets better over time (thresholds, filters, models). This section is about *how* those improvements happen — manually vs. automatically. A solo operator can't manually tune 50 homes. The system has to tune itself for the most part, with a human in the loop only for exceptions.

Four tiers, sized by effort and gated by what's in place underneath them. Each tier maps to a phase from the roadmap above.

### Tier 1 — Self-calibration & self-monitoring (during Phase 1, ~1–2 weeks)

Foundational. None of this is exotic AI — it's standard operational hygiene, and everything in higher tiers depends on it.

- **Auto-baseline calibration.** When RuView's presence flag has been 0 for 30+ minutes, the bridge captures the current CSI baseline and compares it to the install-time baseline. If drift exceeds a tolerance, log "environment changed" and either retune automatically or flag for human review.
- **Threshold control loop.** Rolling 7-day false-alarm rate per home. If it exceeds budget (say >1/week), automatically nudge the threshold up. If a controlled test misses, nudge it down. Slow control — change at most ~5% per week to avoid oscillation.
- **Self-health.** Bridge heartbeat every 30 seconds. Backend alerts if any home goes silent >5 minutes. Sanity checks: CSI flowing, vitals values within physical ranges, no obvious sensor failures.

Build cost: a few hundred lines of code spread across the bridge and backend. Most of it is one control loop.

### Tier 2 — Per-home online learning & fleet anomaly detection (during Phase 2, ~1–2 months)

Now the system starts adapting per-home, not just per-threshold.

- **Per-home online classifier.** Small local model (on the Pi, or in the backend keyed by `home_id`) that updates from labeled events. False-alarm labels become local "negatives" — when something similar happens again, the model is skeptical. Even a weighted nearest-neighbor or logistic-regression model over the vitals window is enough; deep learning not required at this stage.
- **Fleet-wide outlier detection.** Compare each home's metrics to the fleet distribution. Home with 10× the median false-alarm rate? Surface it. Home with controlled-test recall trending down? Surface it.
- **A/B testing harness.** New threshold formulas, new filters, new models — roll to 10% of homes first, compare metrics, auto-rollback on regression. This is the safety net that lets you ship changes confidently without taking the whole fleet down.

Build cost: ~6–8 weeks solo. The A/B harness is the fiddliest piece; the online classifier is genuinely small.

### Tier 3 — LLM operations agent (during Phase 2/3, ~2–3 weeks once Tier 1+2 are in place)

This is the "AI monitoring and adjusting" piece — and the build cost is small *only because* Tier 1+2 already produced the metrics it reads.

- Scheduled run (daily at first, weekly once stable).
- Reads per-home metrics, recent labels, recent events from the backend.
- Produces an action queue. Low-risk actions auto-execute (threshold nudges within bounds, scheduled re-calibration when drift detected). Higher-risk actions queue for human review (deploying a new model version, flagging a customer call).
- Daily output: a short summary in your inbox or Slack — "fleet healthy, 2 homes need attention, here's why."

Example output:

> **Home #042** — false-alarm rate up from 0.4/wk to 3.1/wk over 14 days. Events cluster 7–9pm. New pattern. **Threshold 0.68 → 0.74, auto-applied.**
>
> **Home #018** — zero motion events in 38 hours. Customer on vacation or sensor offline. **Queued for human review.**
>
> **Home #023** — controlled-test recall dropped from 100% to 67% on yesterday's check. Possible degradation. **Re-calibration call scheduled, customer notified.**

Build cost: ~2–3 weeks. Most of the effort is defining the action vocabulary (what is the agent allowed to do unsupervised?) and the safety rails (max changes per home per day, max threshold delta per change). Anthropic or OpenAI API costs are negligible — cents per day at fleet sizes under a few hundred homes.

### Tier 4 — Federated learning & self-adapting models (during Phase 4+, ~3–6 months, ML expertise required)

Research-grade. Genuinely useful if you get there, not a prerequisite for a working product.

- **Federated learning.** Each Pi trains locally on its own labels; only model gradients flow to a central aggregator. Shared model improves without raw CSI ever leaving the home. Big GDPR win. Frameworks exist (Flower, FedML, TensorFlow Federated) but integrating them into a production embedded pipeline is non-trivial.
- **Domain adaptation for new homes.** Models that generalize to a new physical environment with minimal per-home tuning. Active academic area.
- **Auto-detected environment-change recalibration.** Statistical drift detection that triggers re-baseline without human input.

Build cost: significant. Probably gated on outside funding, a strong technical co-founder, or a research partnership with a university group working on CSI sensing.

### What never goes away

Honest list of things the automation layer doesn't replace:

- Hardware physically dying (sensor, Pi, PSU) — alerts you, but a human has to ship the replacement.
- Customer-side changes that break the install (they moved, they replaced their WiFi router, the install code reset).
- Major upstream regressions when you update RuView versions — shadow testing surfaces them, a human decides whether to roll back.
- Anything legal or commercial — billing, GDPR data requests, accidental over-collection.

The automation layer reduces *operational* load. It doesn't replace customer-facing or business-facing work.

### Why this sequencing matters

It's tempting to build the LLM agent (Tier 3) first because it's the most interesting. Don't. Without Tier 1's metrics layer and Tier 2's per-home aggregates, the agent has nothing to read and no safe actions to take. Tier 1 is non-negotiable foundation. Tier 2 is what makes Tier 3 useful. Get them in order.

---

## Cuts From MVP (Still Applies, From v1)

- Multiple family members per home
- Custom branding
- Web dashboard
- Vital signs monitoring as a separate feature (the data is captured, but no dedicated UI for it yet)
- Inactivity alerts
- Multi-home support per family
- Subscription billing
- Cognitum Seed integration
- Custom enclosures

---

## Risks and Mitigations (Updated)

| Risk | Mitigation |
|------|------------|
| ESP32 firmware issues | Day 1–2 buffered for hardware. Pi 5 ordered alongside |
| Fall detection unreliable in real home | Day 6 testing buffer + Day 7 tuning + Phase 1 threshold tuning |
| Push notifications delayed or dropped | Test 20×+ on Day 5; Twilio SMS fallback in v2 |
| **GDPR exposure from storing health-related data** | **Labeling consent is opt-in. Vitals windows (~1 KB/event) stay in EU on Hetzner. Raw CSI capture is separate opt-in. Privacy policy drafted before first non-family pilot. Health data category triggers explicit consent under GDPR Art. 9 — don't ship to strangers until this is reviewed by someone who knows EU privacy law.** |
| **Customers won't bother labeling events** | **Default to one-tap labels in the notification itself (Android allows action buttons on push). Backfill via history screen. If label rate drops below 80% of alerts within a week, treat it as a UX problem, not user laziness — make the prompt more obvious.** |
| **Synthetic falls (you doing controlled drops) don't match real elderly falls** | **Accept this as a model limitation in Phase 1–3. Real-fall data accumulates slowly from actual incidents. Phase 4 ML training should weight real-fall examples higher than controlled tests.** |
| Pi at customer's home crashes silently | Heartbeat from bridge → backend every 30s; alert if quiet for 5 min |
| Burnout from sprint | Day 7 buffer; Phase 1+ is months, not weeks — pace yourself |

---

## Success Criteria

**End of Week 1 (MVP):**
1. Two ESP32 nodes installed in a real home
2. Phone receives alert within 5 seconds of a simulated fall
3. System runs 24 hours without crashing
4. Family member can label any event in one tap
5. Labels appear in the backend with full event context

**End of Month 3 (Phase 1–2, Automation Tier 1–2):**
1. 5–20 pilot homes
2. <1 false alarm per home per week
3. 200+ labeled events in the database
4. Post-event confirmation filter live in the bridge
5. Tier 1 automation live: thresholds auto-tune, baselines auto-recalibrate, dead homes auto-alert
6. Tier 2 in progress: per-home online learning, fleet outlier detection, A/B harness

**End of Month 6 (Phase 2/3, Automation Tier 3):**
1. Custom WASM detector shipped, A/B-tested against baseline
2. LLM operations agent running daily, auto-handling routine adjustments
3. You are reviewing exceptions for ≤30 min/day across the whole fleet
4. Fleet of 20–50 homes operationally sustainable solo

**End of Year 1 (Phase 4, Automation Tier 4 optional):**
1. ML classifier trained on accumulated labeled data, outperforming WASM detector in A/B
2. False-alarm rate at a level where families stop disabling the system
3. Defensible labeled CSI dataset that competitors don't have
4. (Optional) Federated learning prototype in flight or partnership in place to build it

---

## Open Questions That Will Resolve in Phase 1–2

- What's the realistic per-home false-alarm rate with default thresholds in diverse homes? (We genuinely don't know until we test.)
- How quickly does the labeling habit stick for non-technical family members? Does the post-event confirmation filter mean alerts become rare enough that labeling stays engaging?
- What's the legal/consent shape that lets us collect CSI windows from real homes for model training — both GDPR-correct and not scary enough to drive customers away? Talk to an EU privacy lawyer before pilot 5.
- Is mmWave radar (Aqara FP2-class hardware) actually a better underlying sensor for fall detection than WiFi CSI? Keep an eye on this — if it is, the architecture you've built (bridge + backend + app) is portable to a different sensor, but the RuView-specific bits would need to be replaced. The data flywheel survives the swap; the firmware doesn't.
