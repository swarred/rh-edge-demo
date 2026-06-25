from __future__ import annotations
import os
import time
import jwt
from flask import Flask, jsonify, request
from kubernetes import client, config as k8s_config

app = Flask(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET", "rh-edge-node-local-secret")
IDENTITY_SERVICE_URL = os.environ.get("IDENTITY_SERVICE_URL", "")

# Operator definitions — mirrors the MicroShift ServiceAccounts
OPERATORS = {
    "alpha": {
        "callsign": "ALPHA",
        "role": "Fire Control Specialist",
        "clearance": "SECRET",
        "cluster_role": "targeting-specialist",
        "capabilities": ["targeting-data:rw", "roe-cache:r", "strike-package:rw"],
    },
    "bravo": {
        "callsign": "BRAVO",
        "role": "ROE Cache Officer",
        "clearance": "SECRET",
        "cluster_role": "roe-officer",
        "capabilities": ["roe-cache:rw", "golden-dome-policy:rw", "targeting-data:r"],
    },
    "charlie": {
        "callsign": "CHARLIE",
        "role": "Drone Relay Operator",
        "clearance": "SECRET",
        "cluster_role": "drone-relay-operator",
        "capabilities": ["drone-mesh-status:rw", "relay-config:rw", "targeting-data:r"],
    },
    "delta": {
        "callsign": "DELTA",
        "role": "Mission Commander",
        "clearance": "TS/SCI",
        "cluster_role": "mission-commander",
        "capabilities": ["mission-status:rw", "command-log:rw", "*:r"],
    },
}

_mode = "CLOUD"
_last_sync = time.time()
_active_tokens: dict = {}


def _load_k8s():
    try:
        kubeconfig = os.environ.get("KUBECONFIG", "/var/lib/microshift/resources/kubeadmin/kubeconfig")
        k8s_config.load_kube_config(config_file=kubeconfig)
        return client.CoreV1Api(), client.AuthorizationV1Api()
    except Exception:
        return None, None


def _token_ttl():
    # Local mode gives longer TTL — operators can work offline longer
    return 172800 if _mode == "LOCAL" else 300


def _issue_token(callsign: str) -> dict:
    op = OPERATORS[callsign]
    now = time.time()
    ttl = _token_ttl()
    payload = {
        "sub": f"system:serviceaccount:jtac-ops:operator-{callsign}",
        "callsign": op["callsign"],
        "role": op["cluster_role"],
        "capabilities": op["capabilities"],
        "mode": _mode,
        "iat": int(now),
        "exp": int(now + ttl),
        "iss": "rh-edge-node/identity-service",
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    _active_tokens[callsign] = {
        "token": token,
        "issued_at": now,
        "expires_at": now + ttl,
        "mode": _mode,
    }
    return {"token": token, "expires_in": ttl, "mode": _mode}


def _verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


@app.route("/health")
def health():
    return jsonify({"status": "ok", "mode": _mode, "uptime_s": int(time.time() - _start_time)})


@app.route("/operators")
def list_operators():
    now = time.time()
    result = []
    for callsign, op in OPERATORS.items():
        tok = _active_tokens.get(callsign, {})
        expires_in = max(0, tok.get("expires_at", 0) - now) if tok else 0
        result.append({
            "callsign": op["callsign"],
            "role": op["role"],
            "clearance": op["clearance"],
            "cluster_role": op["cluster_role"],
            "capabilities": op["capabilities"],
            "authenticated": callsign in _active_tokens and expires_in > 0,
            "token_expires_in": int(expires_in),
            "token_mode": tok.get("mode") if tok else None,
            "last_auth_ts": tok.get("issued_at") if tok else None,
        })
    return jsonify({
        "operators": result,
        "mode": _mode,
        "last_sync_ts": _last_sync,
        "last_sync_age_s": int(time.time() - _last_sync),
    })


@app.route("/operators/<callsign>/auth", methods=["POST"])
def auth_operator(callsign):
    if callsign not in OPERATORS:
        return jsonify({"error": "unknown operator"}), 404
    result = _issue_token(callsign)
    result["operator"] = OPERATORS[callsign]["callsign"]
    return jsonify(result)


@app.route("/operators/<callsign>/verify", methods=["POST"])
def verify_operator(callsign):
    token = (request.json or {}).get("token", "")
    claims = _verify_token(token)
    if not claims or claims.get("callsign", "").lower() != callsign:
        return jsonify({"valid": False, "reason": "invalid or expired token"}), 401
    return jsonify({"valid": True, "claims": claims})


@app.route("/operators/auth-all", methods=["POST"])
def auth_all():
    """Issue tokens for all operators — called at boot and on link restore."""
    tokens = {}
    for callsign in OPERATORS:
        tokens[callsign] = _issue_token(callsign)
    return jsonify({"tokens_issued": len(tokens), "mode": _mode})


@app.route("/rbac/status")
def rbac_status():
    """Return MicroShift RBAC state for the dashboard artifact panel."""
    core_api, _ = _load_k8s()
    sas = []
    if core_api:
        try:
            sa_list = core_api.list_namespaced_service_account("jtac-ops")
            for sa in sa_list.items:
                annotations = sa.metadata.annotations or {}
                sas.append({
                    "name": sa.metadata.name,
                    "callsign": annotations.get("edge.redhat.com/callsign", ""),
                    "role": annotations.get("edge.redhat.com/role", ""),
                    "clearance": annotations.get("edge.redhat.com/clearance", ""),
                    "created": sa.metadata.creation_timestamp.isoformat() if sa.metadata.creation_timestamp else None,
                })
        except Exception as exc:
            sas = [{"error": str(exc)}]
    return jsonify({
        "namespace": "jtac-ops",
        "service_accounts": sas,
        "mode": _mode,
        "policy_version": _policy_version,
    })


@app.route("/mode", methods=["GET", "POST"])
def mode():
    global _mode, _last_sync
    if request.method == "POST":
        data = request.json or {}
        new_mode = data.get("mode", _mode)
        if new_mode in ("CLOUD", "LOCAL"):
            _mode = new_mode
            if _mode == "CLOUD":
                _last_sync = time.time()
    return jsonify({"mode": _mode, "last_sync_ts": _last_sync})


@app.route("/policy/sync", methods=["POST"])
def policy_sync():
    """Called by Ansible on link restore — marks policy as cloud-synced."""
    global _last_sync, _policy_version
    data = request.json or {}
    _last_sync = time.time()
    _policy_version = data.get("version", _policy_version)
    # Re-issue all tokens with CLOUD mode and fresh TTL
    for callsign in OPERATORS:
        if callsign in _active_tokens:
            _issue_token(callsign)
    return jsonify({"synced": True, "policy_version": _policy_version, "tokens_refreshed": len(_active_tokens)})


_start_time = time.time()
_policy_version = "zta-edge-v3"

if __name__ == "__main__":
    # Issue tokens for all operators at startup
    for c in OPERATORS:
        _issue_token(c)
    app.run(host="0.0.0.0", port=5000)
