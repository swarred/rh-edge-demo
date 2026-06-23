from __future__ import annotations
import os
import time
import threading
import urllib.request
import json
from flask import Flask, render_template, jsonify

app = Flask(__name__)

IDENTITY_URL = os.environ.get("IDENTITY_SERVICE_URL", "http://localhost:5000")

# ── Demo state ────────────────────────────────────────────────────────
_state = {
    "mode": "CLOUD",           # CLOUD | LOCAL
    "link": "CONNECTED",       # CONNECTED | SEVERED
    "trigger_time": None,
    "ansible_step": 0,
    "eda_events": [],
}

# Ansible log steps — shown progressively after trigger
_ANSIBLE_CLOUD_STEPS = [
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

_ANSIBLE_LOCAL_STEPS = [
    (0,  "play",    "PLAY [rh-edge-node — DDIL Local Enforcement]"),
    (2,  "task",    "Gathering Facts"),
    (4,  "ok",      "jtac-ops"),
    (7,  "task",    "enforce_local : set identity-service mode=LOCAL"),
    (9,  "ok",      "jtac-ops"),
    (12, "task",    "enforce_local : extend operator token TTL to 3600s"),
    (14, "changed", "jtac-ops"),
    (17, "task",    "enforce_local : cache golden-dome-policy snapshot"),
    (19, "ok",      "jtac-ops"),
    (22, "task",    "enforce_local : write mission-status link=SEVERED"),
    (24, "changed", "jtac-ops"),
    (27, "recap",   ""),
    (28, "result",  "jtac-ops : ok=4  changed=2  unreachable=0"),
]

_lock = threading.Lock()


def _call(path: str) -> dict | None:
    try:
        req = urllib.request.urlopen(f"{IDENTITY_URL}{path}", timeout=2)
        return json.loads(req.read())
    except Exception:
        return None


def _elapsed() -> float | None:
    t = _state.get("trigger_time")
    return (time.time() - t) if t else None


@app.route("/")
def index():
    return render_template("scenario1.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/status")
def api_status():
    ops_data = _call("/operators") or {}
    rbac_data = _call("/rbac/status") or {}
    e = _elapsed()
    triggered = e is not None

    # Build ansible log lines based on elapsed time
    steps = _ANSIBLE_LOCAL_STEPS if _state["mode"] == "LOCAL" else _ANSIBLE_CLOUD_STEPS
    log_lines = []
    if triggered and e is not None:
        for ts, kind, content in steps:
            if e >= ts:
                log_lines.append({"kind": kind, "content": content, "ts": ts})

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


@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    with _lock:
        _state["trigger_time"] = time.time()
        _state["link"] = "SEVERED"
        _state["mode"] = "LOCAL"
        _state["eda_events"].append({
            "ts": time.time(),
            "source": "EDA",
            "msg": "EW jamming detected — link loss confirmed",
            "level": "warn",
        })
        _state["eda_events"].append({
            "ts": time.time(),
            "source": "EDA",
            "msg": 'Rule "DDIL Detected" fired — job queued',
            "level": "info",
        })
        _state["eda_events"].append({
            "ts": time.time(),
            "source": "ANSIBLE",
            "msg": "enforce_local playbook starting on rh-edge-node",
            "level": "info",
        })
    # Tell identity service to switch to LOCAL mode
    try:
        data = json.dumps({"mode": "LOCAL"}).encode()
        req = urllib.request.Request(
            f"{IDENTITY_URL}/mode",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass
    return jsonify({"ok": True, "mode": "LOCAL"})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    with _lock:
        _state["trigger_time"] = None
        _state["link"] = "CONNECTED"
        _state["mode"] = "CLOUD"
        _state["eda_events"] = []
    try:
        data = json.dumps({"mode": "CLOUD"}).encode()
        req = urllib.request.Request(
            f"{IDENTITY_URL}/mode",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
        # Re-auth all operators
        urllib.request.urlopen(
            urllib.request.Request(f"{IDENTITY_URL}/operators/auth-all", method="POST"),
            timeout=2,
        )
    except Exception:
        pass
    return jsonify({"ok": True, "mode": "CLOUD"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8888, debug=False)
