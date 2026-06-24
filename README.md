# Red Hat Software-Defined Mission Edge Demo

Live demonstration of Red Hat Device Edge capabilities across three mission vignettes from the Software-Defined Warfare (SDW) framework, targeting USSF/DAF DDIL and kill-chain resilience requirements.

**Scenarios:**
| # | Title | Status |
|---|---|---|
| 1 | Zero-Trust Identity Continuity — JTAC DDIL Tactical Edge | ✅ Implemented |
| 3 | Wearable Edge — F-35 Human-Machine Teaming | ✅ Implemented |
| 4 | Multi-Domain Sensor Fusion — Golden Dome Early Warning | ✅ Implemented |

The interactive demo preview (talking points, architecture summary, and scenario overview) lives at **`docs/index.html`** — open it in a browser before the live demo to orient the audience.

---

## Prerequisites

You need all of the following before running this demo.

### Local tooling

| Tool | Purpose | Install |
|---|---|---|
| `podman` | Build and run rootful containers | `dnf install podman` |
| `ansible` | Run the deployment playbook | `dnf install ansible-core` |
| `ansible-rulebook` | Event-driven automation (EDA) | `pip install ansible-rulebook` |
| `virt-install` + `libvirt` | Create and manage the edge VM | `dnf install virt-install libvirt` |
| `virsh` | Manage VM lifecycle | Included with libvirt |
| `sshpass` | Password-based SSH in automation | `dnf install sshpass` |
| `oc` CLI | Interact with OCP cluster | [Download from console.redhat.com](https://console.redhat.com/openshift/downloads) |
| `skopeo` | (Optional) Inspect registry image tags | `dnf install skopeo` |

### Accounts and access

| Requirement | Why | Where to get it |
|---|---|---|
| **Red Hat account** (access.redhat.com) | Subscribe the VM to pull MicroShift RPMs during build | [register.redhat.com](https://register.redhat.com) |
| **Red Hat subscription** with MicroShift entitlement | Required to access `rhocp-4.22-for-rhel-9` repos | Included with Red Hat Device Edge or OpenShift subscription |
| **OCP cluster** (4.12+, **3-master minimum**) with Skupper v2 operator installed | Hosts the ground station — Skupper site, AccessGrant, ZTA policy ConfigMaps, and ACM hub for Scenario 4. Single-master clusters crash under ACM + Skupper load. | Your cluster or [console.redhat.com/openshift](https://console.redhat.com/openshift) |
| **OCP pull secret** | Lets the bootc image pull from `registry.redhat.io` | Extracted automatically from your logged-in cluster by `setup-creds.sh` |

### Repos

Clone both repos side by side:

```bash
git clone https://github.com/swarred/rh-edge-demo
git clone https://github.com/swarred/rh-edge-demo-automation
```

```
~/
├── rh-edge-demo/           # bootc image + dashboard + EDA + Ansible
└── rh-edge-demo-automation/ # deployment playbook + credential setup
```

---

## First-time setup

### 1. Log into your OCP cluster

```bash
oc login --server=https://<your-cluster-api>:6443
```

### 2. Set up credentials

Run the setup script — it extracts the OCP pull secret and prompts for your Red Hat account credentials. These are stored in `.creds/` (gitignored, never committed):

```bash
cd rh-edge-demo-automation
bash setup-creds.sh
```

You'll need:
- Your **Red Hat username** (email address for access.redhat.com)
- Your **Red Hat password**

> If your machine crashes or reboots and `.creds/` is gone, just re-run `setup-creds.sh`.

### 3. Ensure libvirt is running

```bash
sudo systemctl enable --now libvirtd
sudo virsh net-start default   # starts the virbr0 bridge
```

---

## Running the demo

The full deployment is one command:

```bash
cd rh-edge-demo-automation
ansible-playbook site.yml --ask-become-pass
```

This will:
1. Set up the Skupper site and AccessGrant on your OCP cluster
2. Build the bootc edge node image (~15–25 min on first run, fast from cache after)
3. Convert the bootc image to QCOW2 via `bootc-image-builder` (~10–15 min)
4. Render cloud-init with the live Skupper token
5. Create and start the edge VM (8 vCPU, 8GB RAM)
6. Wait for the dashboard to be ready and print the URL

When it completes, open the printed URL in a browser (e.g. `http://192.168.122.131:8888`).

> **Note:** The QCOW2 conversion step is skipped if `output/qcow2/disk.qcow2` already exists. Delete `output/` to force a rebuild: `sudo rm -rf output/`

---

## Dashboard

The dashboard runs on the edge VM at port **8888** and is accessible from the host machine via the libvirt bridge network (`192.168.122.x`).

Navigate between scenarios using the tabs in the header.

### Scenario 1 — JTAC DDIL Identity Continuity

Shows a JTAC team's four-operator edge kit maintaining identity and policy autonomously when adversary EW severs all reach-back.

**Demo flow:**
1. Open the dashboard — all four operators (ALPHA, BRAVO, CHARLIE, DELTA) are authenticated in CLOUD mode with 5-minute token TTLs
2. Press **SIMULATE EW JAMMING**
3. Watch the radio switch to DDIL mode — EW static appears, signal rings disappear
4. EDA rulebook fires `enforce-local.yml` — token TTLs extend from 5 min → 60 min (bar slows visibly on operator cards)
5. Ansible log replays the policy enforcement steps in the right panel
6. Press **RESTORE LINK** — Ansible syncs policy from OCP and tokens refresh to CLOUD mode

**What to highlight:**
- Operators never lose access — MicroShift RBAC enforces identity locally
- Token TTL extension is automatic — no manual intervention
- Policy snapshot cached to disk — survives indefinitely without OCP

### Scenario 3 — F-35 Human-Machine Teaming

Shows a pilot's HMDS (Helmet-Mounted Display System) view as onboard AI fuses data from three OCP-hosted sources via Skupper to generate a maneuver directive in under 200ms.

**Demo flow:**
1. Switch to **S-3 F-35 HMT** in the nav
2. Press **DETECT HYPERSONIC THREAT**
3. Bogey appears on the HMDS visor (top-right) and moves toward center
4. Watch Skupper connectors acquire data:
   - **CCA Swarm** — 6 drone track feeds (t≈8s)
   - **Ground Radar** — closure rate and intercept window (t≈14s)
   - **Golden Dome** — threat classification (t≈17s)
5. `phi-4-mini` fuses all three sources on the edge node — inference completes in 187ms
6. Maneuver directive appears on the visor: **BREAK LEFT · 4G · CHAFF ×2**
7. Press **APPROVE MANEUVER** — CCA swarm executes, G-meter climbs, threat marked NEUTRALIZED

**What to highlight:**
- All AI inference runs on the edge node — no cloud dependency
- Data arrives via Skupper/RHSI from OCP-hosted sources — same connectivity story as S1
- Pilot stays in the loop — maneuver requires explicit approval before execution

### Scenario 4 — Golden Dome Sensor Fusion

Shows a PWSA LEO satellite running RHEL Image Mode detecting a hypersonic glide vehicle salvo, classifying it onboard with phi-4-mini, and disseminating verified tracks to four joint-force ground nodes in 7.8 seconds via RHSI.

**Demo flow:**
1. Switch to **S-4 Golden Dome** in the nav
2. A 5-second countdown auto-triggers the satellite pass — no button press needed
3. Watch PWSA-07 move along the orbital arc toward the AOI (North Korea/East Asia area)
4. Satellite sensor glows red as it passes over — AOI burst and HGV tracks appear
5. phi-4-mini classifies the threat onboard (no raw downlink) — right panel shows inference
6. RHSI space-to-ground Skupper links illuminate in sequence:
   - **PACAF TOC** (Hickam AFB) — +3.2s
   - **USS Burke DDG** (SPY-6 radar) — +6.1s
   - **JTAC FWD-001** (W. Pacific) — +9.0s
   - **Golden Dome Battery** (intercept) — +12.4s
7. All four ACM cluster rows flip to **● Ready** in the right panel
8. Timer completes: **"ALL NODES — JOINT FORCE NOTIFIED IN 7.8s"**

**What to highlight:**
- Inference happens on-orbit before any downlink — conserves bandwidth
- Only verified tracks leave the satellite, not raw sensor data
- ACM manages the full fleet (satellite cluster + all ground clusters) from a single pane
- Same RHSI/Skupper connectivity pattern as S1 and S3, extended to space-to-ground

---

## ACM fleet (Scenario 4)

Scenario 4 requires Red Hat Advanced Cluster Management (ACM) installed on the OCP hub. ACM manages a fleet of 5 stub ManagedClusters representing the distributed kill chain, plus `local-cluster` (the OCP hub itself).

### Cluster size requirement

**The OCP hub must be a 3-master cluster.** A single-master OCP cluster crashes under the combined load of ACM MultiClusterHub, Skupper, and the dashboard backend. This was confirmed during development — do not attempt to run the full Scenario 4 stack on a compact/single-node cluster.

### Install ACM

```bash
bash ocp/acm/install-acm.sh
```

The script installs the ACM operator from OperatorHub and waits for `MultiClusterHub` to reach `Running` status (~5–10 min).

### Apply managed cluster stubs

```bash
oc apply -f ocp/acm/managed-clusters.yaml
```

This creates 5 ManagedCluster objects in the `mission-edge` ClusterSet:

| Cluster name | Domain | Represents |
|---|---|---|
| `sat-edge-01` | orbital | PWSA-07 LEO satellite (phi-4-mini onboard, RHEL Image Mode) |
| `pacaf-toc-001` | ground-station | PACAF TOC, Hickam AFB — C2 operations |
| `uss-burke-ddg` | naval | USS Arleigh Burke DDG — SPY-6 radar |
| `jtac-fwd-001` | tactical-edge | JTAC forward element, W. Pacific |
| `golden-dome-bty` | interceptor | Golden Dome intercept battery |

The clusters show as **Offline/Unknown** in the ACM console — visually correct for a demo of intermittently-connected space and edge nodes.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  OCP Ground Station                                                  │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │  Skupper Site   │  │  ZTA Policy      │  │  S3 Data Sources   │  │
│  │  (AccessGrant)  │  │  ConfigMaps      │  │  CCA / Radar /     │  │
│  └────────┬────────┘  └────────┬─────────┘  │  Golden Dome       │  │
└───────────┼────────────────────┼────────────┴────────────────────┘  │
            │  RHSI tunnel       │  Skupper connectors                 │
            │  (can sever)       │                                     │
┌───────────▼────────────────────▼────────────────────────────────────┐│
│  RHEL 9.8 bootc Edge Node (immutable image — MicroShift 4.22)        │
│                                                                      │
│  identity-service  dashboard  EDA rulebook  Ansible  Ollama/phi4    │
│  (JWT / CLOUD-LOCAL mode)     (RHSI health  (enforce- (onboard AI)  │
│                                monitor)      local /                 │
│                                              push-zta)               │
└──────────────────────────────────────────────────────────────────────┘
```

### Red Hat technologies

| Component | Technology |
|---|---|
| Base OS | RHEL 9.8 (bootc immutable image) |
| Lightweight Kubernetes | MicroShift 4.22 |
| Edge connectivity | Red Hat Service Interconnect (Skupper v2) |
| Event-driven automation | ansible-rulebook (EDA) |
| Policy enforcement | Ansible Automation Platform playbooks |
| Onboard AI | Ollama + phi4-mini |
| Image delivery | bootc / podman / bootc-image-builder |

---

## Repository structure

```
rh-edge-demo/
├── Containerfile                   # bootc image (RHEL 9.8 + MicroShift 4.22)
├── identity-service/               # Flask JWT service — CLOUD/LOCAL mode switching
├── dashboard/
│   ├── app.py                      # Flask app — multi-scenario routing
│   ├── templates/
│   │   ├── scenario1.html          # S1: JTAC DDIL dashboard
│   │   ├── scenario3.html          # S3: F-35 HMDS dashboard
│   │   └── scenario4.html          # S4: Golden Dome sensor fusion dashboard
│   └── static/css/
├── eda/rulebook.yml                # ansible-rulebook — monitors RHSI, fires playbooks
├── ansible/
│   ├── enforce-local.yml           # DDIL: switch to LOCAL, extend TTLs
│   └── push-zta-policy.yml         # Link restore: sync policy from OCP
├── microshift/
│   ├── config/config.yaml
│   └── manifests/                  # Auto-applied: namespace, RBAC, ConfigMaps
├── skupper/                        # Edge Skupper site + OCP connector
├── ocp/                            # OCP-side: namespace, Skupper site, AccessGrant
│   └── acm/                        # ACM operator install + managed-cluster stubs
├── docs/index.html                 # Interactive demo preview (open before live demo)
├── cloud-init/user-data            # First-boot: Skupper token, pull secret
└── systemd/                        # Enabled services: identity, dashboard, EDA, Skupper, Ollama
```

---

## Troubleshooting

### `.creds/` directory missing after reboot
Re-run `setup-creds.sh`. The credentials directory is intentionally gitignored.

### Build fails on MicroShift RPM repos
Confirm your Red Hat account has a MicroShift/Device Edge entitlement. The repos required are:
- `rhocp-4.22-for-rhel-9-x86_64-rpms`
- `fast-datapath-for-rhel-9-x86_64-rpms`

### VM boots but dashboard unreachable
SSH into the VM (`ssh demo@<vm-ip>`, password: `redhat`) and check:
```bash
systemctl status dashboard identity-service microshift
journalctl -u dashboard -n 30
```

### skupper-init fails / Skupper tunnel not establishing
Check that the OCP AccessGrant is still valid:
```bash
oc get accessgrant edge-node-token -n jtac-ops
```
If expired or redemptions exhausted, re-run `ansible-playbook site.yml --ask-become-pass` to create a new grant.

### VM shows IP but services not ready
MicroShift takes 2–3 minutes to fully start after boot. Wait and retry.

---

## Build notes

- **`--memory=6g`** on the podman build command limits memory pressure during the MicroShift RPM download step, preventing kernel OOM crashes on systems without ECC RAM.
- **MicroShift 4.22 on RHEL 10** is not available — CDN repos return 404 as of 2026-06-23. This demo uses RHEL 9.8 + MicroShift 4.22, which is a fully supported and tested pairing.
- The bootc image is **immutable** — changes to dashboard templates or app code require a full rebuild and VM redeploy.
- **`bootc-image-builder` image pin:** use `registry.redhat.io/rhel9/bootc-image-builder:9.8-1782204946`. Later tags have shown conversion regressions on RHEL 9.8 QCOW2 output.
- **Skupper router pinned to 3.4.2** in the Containerfile and skupper manifests. Later 3.x builds introduced a regression in the AccessGrant redemption flow that breaks the edge-to-OCP tunnel on first boot.
- **Python 3.9 compatibility** — `dashboard/app.py` uses `Union[X, Y]` type annotations rather than the `X | Y` shorthand, which is 3.10+. Do not upgrade to the pipe-style union syntax without first confirming the Python version in the bootc image.
- **MicroShift `clusterNetwork` format** — the `config.yaml` under `microshift/config/` uses the list-of-objects format (`- cidr: 10.42.0.0/16`) rather than the bare string format. The bare string format was silently accepted in earlier MicroShift 4.x builds but fails validation in 4.22.
