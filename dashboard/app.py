from __future__ import annotations
import os
import time
import threading
import urllib.request
import json
from flask import Flask, render_template, jsonify, redirect, url_for

app = Flask(__name__)

IDENTITY_URL = os.environ.get("IDENTITY_SERVICE_URL", "http://localhost:5000")

# ── Shared identity state ─────────────────────────────────────────────
_state = {
    "mode": "CLOUD",
    "link": "CONNECTED",
    "eda_events": [],
}

# ── S1 state ──────────────────────────────────────────────────────────
_s1 = {"trigger_time": None}

# ── S3 state ──────────────────────────────────────────────────────────
_s3 = {"trigger_time": None, "approved": False, "approved_time": None}

# ── S4 state ──────────────────────────────────────────────────────────
_s4 = {"trigger_time": None}

_lock = threading.Lock()

# ── Ansible log steps ─────────────────────────────────────────────────
_ANSIBLE_LOCAL = [
    (0,  "play",    "PLAY [rh-edge-node — DDIL Local Enforcement]"),
    (2,  "task",    "Gathering Facts"),
    (4,  "ok",      "jtac-ops"),
    (7,  "task",    "enforce_local : set identity-service mode=LOCAL"),
    (9,  "ok",      "jtac-ops"),
    (12, "task",    "enforce_local : extend operator token TTL to 172800s (48h)"),
    (14, "changed", "jtac-ops"),
    (17, "task",    "enforce_local : cache golden-dome-policy snapshot"),
    (19, "ok",      "jtac-ops"),
    (22, "task",    "enforce_local : write mission-status link=SEVERED"),
    (24, "changed", "jtac-ops"),
    (27, "recap",   ""),
    (28, "result",  "jtac-ops : ok=4  changed=2  unreachable=0"),
]

_ANSIBLE_CLOUD = [
    (0,  "play",    "PLAY [rh-edge-node — ZTA Policy Push]"),
    (3,  "task",    "Gathering Facts"),
    (5,  "ok",      "jtac-ops"),
    (9,  "task",    "zta_policy : verify MicroShift API reachable"),
    (11, "ok",      "jtac-ops"),
    (15, "task",    "zta_policy : apply roe-cache ConfigMap update"),
    (19, "changed", "jtac-ops"),
    (23, "task",    "zta_policy : refresh operator token TTLs"),
    (27, "ok",      "jtac-ops"),
    (31, "task",    "zta_policy : POST /policy/sync to identity-service"),
    (35, "ok",      "jtac-ops"),
    (39, "recap",   ""),
    (40, "result",  "jtac-ops : ok=5  changed=1  unreachable=0"),
]

# ── S4 dissemination steps ───────────────────────────────────────────
_S4_STEPS = [
    (0,  "SAT",      "PWSA-07: orbital pass — approaching AOI"),
    (3,  "DETECT",   "Unknown threat detected — 3 tracks acquired"),
    (6,  "AI",       "phi-4-mini (RHEL Image Mode): UNKNOWN_THREAT — 94% conf"),
    (9,  "RHSI",     "Space-to-ground Skupper link established"),
    (12, "PACAF",    "PACAF-TOC-001: verified track received"),
    (15, "NAVY",     "USS-BURKE-DDG: SPY-6 radar cueing initiated"),
    (18, "JTAC",     "JTAC-FWD-001: track received — operators alerted"),
    (21, "DOME",     "INTERCEPT-BTY: OPIR track correlated — intercept solution computed"),
    (23, "COMPLETE", "DISSEMINATION COMPLETE — 7.8s · 4 nodes notified"),
]

# ── S3 RHSI feed steps ────────────────────────────────────────────────
_S3_FEED_STEPS = [
    (2,  "THREAT",   "Unknown threat detected — track initiated"),
    (5,  "RHSI",     "Skupper connector: CCA-swarm-feed — ACQUIRING"),
    (8,  "RHSI",     "Skupper connector: CCA-swarm-feed — 6 feeds FUSED"),
    (11, "RHSI",     "Skupper connector: gnd-radar-track — ACQUIRING"),
    (14, "RHSI",     "Skupper connector: gnd-radar-track — FUSED"),
    (17, "RHSI",     "Skupper connector: opir-track — CORRELATED"),
    (19, "AI",       "phi-4-mini: fusing 3 data sources — PROCESSING"),
    (21, "AI",       "phi-4-mini: inference complete — 187ms"),
    (22, "RECOMMEND","BREAK LEFT / 4G / CHAFF × 2 — confidence: 97%"),
]


def _call(path: str) -> dict | None:
    try:
        req = urllib.request.urlopen(f"{IDENTITY_URL}{path}", timeout=2)
        return json.loads(req.read())
    except Exception:
        return None


def _elapsed(state_dict: dict) -> float | None:
    t = state_dict.get("trigger_time")
    return (time.time() - t) if t else None


# ── Routes ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return redirect(url_for("scenario", n=1))


@app.route("/scenario/<int:n>")
def scenario(n):
    if n not in (1, 3, 4):
        return redirect(url_for("scenario", n=1))
    return render_template(f"scenario{n}.html", active=n)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ── Shared identity status (used by both scenarios) ───────────────────
@app.route("/api/status")
def api_status():
    ops_data = _call("/operators") or {}
    rbac_data = _call("/rbac/status") or {}
    e = _elapsed(_s1)
    triggered = e is not None
    steps = _ANSIBLE_LOCAL if _state["mode"] == "LOCAL" else _ANSIBLE_CLOUD
    log_lines = [
        {"kind": kind, "content": content, "ts": ts}
        for ts, kind, content in steps
        if triggered and e is not None and e >= ts
    ]
    return jsonify({
        "mode": _state["mode"],
        "link": _state["link"],
        "triggered": triggered,
        "elapsed": int(e) if e else 0,
        "operators": ops_data.get("operators", []),
        "last_sync_age_s": ops_data.get("last_sync_age_s", 0),
        "policy_version": rbac_data.get("policy_version", "zta-edge-v3"),
        "ansible_log": log_lines,
        "eda_events": _state["eda_events"][-8:],
    })


# ── S3 status ─────────────────────────────────────────────────────────
@app.route("/api/status/3")
def api_status_s3():
    ops_data = _call("/operators") or {}
    e = _elapsed(_s3)
    ea = (_s3["approved_time"] and time.time() - _s3["approved_time"])

    feed_events = [
        {"ts": ts, "source": src, "msg": msg}
        for ts, src, msg in _S3_FEED_STEPS
        if e is not None and e >= ts
    ] if e is not None else []

    # Bogey state
    bogey_visible  = e is not None and e >= 2
    bogey_tracking = e is not None and e >= 5
    bogey_locked   = e is not None and e >= 14
    bogey_neutralized = _s3["approved"] and ea and ea >= 4

    # Data feed states
    def feed_state(on_at, fused_at):
        if e is None:            return "offline"
        if e < on_at:            return "offline"
        if e < fused_at:         return "acquiring"
        return "fused"

    rec_ready = e is not None and e >= 22
    approve_active = rec_ready and not _s3["approved"]

    return jsonify({
        "triggered": e is not None,
        "elapsed": int(e) if e else 0,
        "approved": _s3["approved"],
        "approved_elapsed": int(ea) if ea else 0,
        "bogey_visible": bogey_visible,
        "bogey_tracking": bogey_tracking,
        "bogey_locked": bogey_locked,
        "bogey_neutralized": bogey_neutralized,
        "feed_cca":  feed_state(5, 8),
        "feed_radar": feed_state(11, 14),
        "feed_dome": feed_state(17, 17),
        "rec_ready": rec_ready,
        "approve_active": approve_active,
        "feed_events": feed_events,
        "operators": ops_data.get("operators", []),
        "mode": _state["mode"],
        "link": _state["link"],
    })


# ── S1 trigger / reset ────────────────────────────────────────────────
@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    with _lock:
        _s1["trigger_time"] = time.time()
        _state["link"] = "SEVERED"
        _state["mode"] = "LOCAL"
        _state["eda_events"].append({"ts": time.time(), "source": "EDA",
            "msg": "EW jamming detected — link loss confirmed", "level": "warn"})
        _state["eda_events"].append({"ts": time.time(), "source": "EDA",
            "msg": 'Rule "DDIL Detected" fired — job queued', "level": "info"})
        _state["eda_events"].append({"ts": time.time(), "source": "ANSIBLE",
            "msg": "enforce_local playbook starting on rh-edge-node", "level": "info"})
    try:
        data = json.dumps({"mode": "LOCAL"}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"{IDENTITY_URL}/mode", data=data,
            headers={"Content-Type": "application/json"}, method="POST"), timeout=2)
        urllib.request.urlopen(urllib.request.Request(
            f"{IDENTITY_URL}/operators/auth-all", method="POST"), timeout=2)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    with _lock:
        _s1["trigger_time"] = None
        _state["link"] = "CONNECTED"
        _state["mode"] = "CLOUD"
        _state["eda_events"] = []
    try:
        data = json.dumps({"mode": "CLOUD"}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"{IDENTITY_URL}/mode", data=data,
            headers={"Content-Type": "application/json"}, method="POST"), timeout=2)
        urllib.request.urlopen(urllib.request.Request(
            f"{IDENTITY_URL}/operators/auth-all", method="POST"), timeout=2)
    except Exception:
        pass
    return jsonify({"ok": True})


# ── S3 trigger / reset / approve ─────────────────────────────────────
@app.route("/api/trigger/3", methods=["POST"])
def api_trigger_s3():
    with _lock:
        _s3["trigger_time"] = time.time()
        _s3["approved"] = False
        _s3["approved_time"] = None
    return jsonify({"ok": True})


@app.route("/api/reset/3", methods=["POST"])
def api_reset_s3():
    with _lock:
        _s3["trigger_time"] = None
        _s3["approved"] = False
        _s3["approved_time"] = None
    return jsonify({"ok": True})


@app.route("/api/approve/3", methods=["POST"])
def api_approve_s3():
    with _lock:
        _s3["approved"] = True
        _s3["approved_time"] = time.time()
    return jsonify({"ok": True})


# ── S4 status / trigger / reset ───────────────────────────────────────
@app.route("/api/status/4")
def api_status_s4():
    e = _elapsed(_s4)
    steps = [
        {"ts": ts, "source": src, "msg": msg}
        for ts, src, msg in _S4_STEPS
        if e is not None and e >= ts
    ] if e is not None else []

    return jsonify({
        "triggered": e is not None,
        "elapsed": int(e) if e else 0,
        "steps": steps,
        "sat_over_aoi":   e is not None and e >= 3,
        "ai_complete":    e is not None and e >= 6,
        "rhsi_up":        e is not None and e >= 9,
        "node_pacaf":     e is not None and e >= 12,
        "node_burke":     e is not None and e >= 15,
        "node_jtac":      e is not None and e >= 18,
        "node_dome":      e is not None and e >= 21,
        "complete":       e is not None and e >= 23,
    })


@app.route("/api/trigger/4", methods=["POST"])
def api_trigger_s4():
    with _lock:
        _s4["trigger_time"] = time.time()
    return jsonify({"ok": True})


@app.route("/api/reset/4", methods=["POST"])
def api_reset_s4():
    with _lock:
        _s4["trigger_time"] = None
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8888, debug=False)
