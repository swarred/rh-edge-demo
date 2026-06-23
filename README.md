# Red Hat Software-Defined Mission Edge Demo

Live demonstration of Red Hat Device Edge capabilities across three mission vignettes from the Software-Defined Warfare (SDW) framework, targeting USSF/DAF DDIL and kill-chain resilience requirements.

**Selected vignettes:**
- **Scenario 1 — Zero-Trust Identity Continuity in DDIL** *(implemented in this repo)*
- **Scenario 3 — Wearable Edge for Human-Machine Teaming** *(planned)*
- **Scenario 4 — Multi-Domain Sensor Fusion for Golden Dome Early Warning** *(planned)*

---

## Scenario 1: DDIL Identity Continuity

### Mission Context

A four-man JTAC team is calling in strikes in contested territory when adversary EW severs all reach-back links. Normally, the central identity provider goes unreachable and every device locks out. This demo shows how Red Hat Device Edge maintains local identity validation autonomously — operators continue passing targeting data, receiving cached policy updates, and keeping the sensor-to-shooter loop alive for 48+ hours without any manual intervention.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  OCP Ground Station (cloud/HQ)                                  │
│  ┌───────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │  Skupper Site │  │  ZTA Policy     │  │  Ansible         │  │
│  │  (RHSI)       │  │  ConfigMaps     │  │  Automation      │  │
│  └──────┬────────┘  └────────┬────────┘  └─────────┬────────┘  │
└─────────┼───────────────────┼─────────────────────┼────────────┘
          │  RHSI Tunnel      │  Policy Sync         │  Playbooks
          │  (link can sever) │                      │
┌─────────▼───────────────────▼─────────────────────▼────────────┐
│  RHEL 9.8 bootc Edge Node (immutable image)                     │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  MicroShift 4.22 (jtac-ops namespace)                    │   │
│  │                                                          │   │
│  │  ServiceAccounts:  ALPHA · BRAVO · CHARLIE · DELTA       │   │
│  │  ClusterRoles:     targeting-specialist · roe-officer    │   │
│  │                    drone-relay-operator · mission-commander│  │
│  │  ConfigMaps:       targeting-data · roe-cache            │   │
│  │                    golden-dome-policy · mission-status   │   │
│  │                    drone-mesh-status                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ identity-service│  │   dashboard      │  │  EDA rulebook │  │
│  │ (Flask/JWT)     │  │   (Flask)        │  │  (ansible-    │  │
│  │                 │  │                  │  │   rulebook)   │  │
│  │ - CLOUD/LOCAL   │  │ - Live operator  │  │               │  │
│  │   mode switch   │  │   status         │  │ - Monitors    │  │
│  │ - Issues JWTs   │  │ - Ansible log    │  │   RHSI health │  │
│  │ - Token TTL     │  │   replay         │  │ - Triggers    │  │
│  │   extends in    │  │ - Mode indicator │  │   enforce-    │  │
│  │   LOCAL mode    │  │                  │  │   local.yml   │  │
│  └────────┬────────┘  └──────────────────┘  └──────┬────────┘  │
│           │                                         │           │
│  ┌────────▼─────────────────────────────────────────▼────────┐  │
│  │  Ansible Playbooks                                        │  │
│  │  enforce-local.yml  — set LOCAL mode, extend TTLs,       │  │
│  │                        snapshot golden-dome-policy        │  │
│  │  push-zta-policy.yml — sync from OCP on link restore,    │  │
│  │                         refresh tokens to CLOUD mode      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  Skupper router  │  │  Ollama (phi4)   │                    │
│  │  (RHSI tunnel    │  │  offline AI for  │                    │
│  │   to OCP)        │  │  autonomous ops  │                    │
│  └──────────────────┘  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

### DDIL Flow

**Link severed (DDIL detected):**
1. EDA rulebook detects RHSI health endpoint goes `down`
2. Triggers `enforce-local.yml`
3. identity-service switches to `LOCAL` mode — token TTL extends from 5 min → 60 min
4. Golden Dome policy ConfigMap snapshot written to local disk
5. `mission-status` ConfigMap updated: `link=SEVERED, mode=LOCAL`
6. Dashboard reflects DDIL state; operators continue working

**Link restored:**
1. EDA rulebook detects RHSI health endpoint returns `up`
2. Triggers `push-zta-policy.yml`
3. Policy synced from OCP; tokens re-issued with `CLOUD` mode TTL
4. `mission-status` updated: `link=CONNECTED, mode=CLOUD`
5. Dashboard returns to nominal state

### Operator Roles

| Callsign | Role | Clearance | Key Capabilities |
|---|---|---|---|
| ALPHA | Fire Control Specialist | SECRET | targeting-data:rw, roe-cache:r, strike-package:rw |
| BRAVO | ROE Cache Officer | SECRET | roe-cache:rw, golden-dome-policy:rw, targeting-data:r |
| CHARLIE | Drone Relay Operator | SECRET | drone-mesh-status:rw, relay-config:rw, targeting-data:r |
| DELTA | Mission Commander | TS/SCI | mission-status:rw, command-log:rw, *:r |

### Red Hat Technologies

| Component | Technology |
|---|---|
| Base OS | RHEL 9.8 (bootc immutable image) |
| Lightweight Kubernetes | MicroShift 4.22 |
| Edge connectivity | Red Hat Service Interconnect (Skupper) |
| Identity & JWT | identity-service (Python/Flask, custom) |
| Event-driven automation | ansible-rulebook (EDA) |
| Policy enforcement | Ansible Automation Platform playbooks |
| Offline AI | Ollama + phi4-mini |
| Image delivery | bootc / podman |

---

## Repository Structure

```
rh-edge-demo/
├── Containerfile              # bootc image definition (RHEL 9.8 + MicroShift 4.22)
├── identity-service/          # Flask JWT identity service (CLOUD/LOCAL mode)
│   ├── app.py
│   └── templates/
├── dashboard/                 # Flask status dashboard with live EDA/Ansible log replay
│   ├── app.py
│   ├── templates/
│   └── static/
├── eda/
│   └── rulebook.yml           # ansible-rulebook: monitors RHSI health, triggers playbooks
├── ansible/
│   ├── enforce-local.yml      # DDIL enforcement playbook
│   ├── push-zta-policy.yml    # Link-restore policy sync playbook
│   └── roles/
├── microshift/
│   ├── config/config.yaml     # MicroShift node config
│   └── manifests/             # Auto-applied at every MicroShift start
│       ├── 00-namespace.yaml  # jtac-ops namespace
│       ├── 01-rbac.yaml       # ServiceAccounts, ClusterRoles, bindings, ConfigMaps
│       ├── 02-identity-service.yaml
│       └── 03-dashboard.yaml
├── skupper/
│   ├── site.yaml              # Skupper site config (token injected via cloud-init)
│   └── connector.yaml
├── cloud-init/
│   └── user-data              # First-boot config: Skupper token, env vars
└── systemd/                   # Service units enabled in image
    ├── identity-service.service
    ├── dashboard.service
    ├── skupper-init.service
    ├── eda-server.service
    └── ollama.service
```

---

## Build

### Prerequisites

- Podman with rootful build support
- Access to OCP cluster (for pull secret)
- Red Hat subscription account (for MicroShift RPM repos)
- `rh-edge-demo-automation` repo cloned alongside this one

### Credential setup

Credentials are never baked into the image. Run the setup script once (or after any crash/reboot that clears `.creds/`):

```bash
oc login   # ensure logged into your OCP cluster
cd ../rh-edge-demo-automation && bash setup-creds.sh
```

This extracts the OCP pull secret and prompts for your Red Hat account credentials, saving both to `rh-edge-demo-automation/.creds/` (gitignored).

### Build the image

```bash
cd /path/to/rh-edge-demo-automation
sudo podman build \
  --memory=6g \
  --authfile .creds/pull-secret.json \
  --secret id=rhsm-user,src=.creds/rhsm-user.txt \
  --secret id=rhsm-pass,src=.creds/rhsm-pass.txt \
  -t localhost/rh-edge-node:latest \
  ../rh-edge-demo
```

> Note: `--memory=6g` limits memory pressure during the MicroShift RPM download step. Build takes ~15–25 minutes on first run.

### Deploy

```bash
cd ../rh-edge-demo-automation
ansible-playbook site.yml --ask-become-pass
```

---

## Known Issues / Build Notes

- **MicroShift 4.22 on RHEL 10**: `rhocp-4.22-for-rhel-10-x86_64-rpms` is not yet published on the Red Hat CDN as of 2026-06-23 (Tech Preview listed in docs but packages unavailable). Using RHEL 9.8 + MicroShift 4.22, which is a fully supported pairing.
