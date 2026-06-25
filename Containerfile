FROM registry.redhat.io/rhel9/rhel-bootc:9.8
ARG USHIFT_VER=4.22

# ── Subscription + MicroShift repos ──────────────────────────────────
# Red Hat credentials injected at build time via --secret.
# Credentials never written into any image layer — container unregisters
# itself before dnf clean all.
#
# Build with:
#   sudo podman build \
#     --authfile .creds/pull-secret.json \
#     --secret id=rhsm-user,src=.creds/rhsm-user.txt \
#     --secret id=rhsm-pass,src=.creds/rhsm-pass.txt \
#     -t localhost/rh-edge-node:latest .
RUN --mount=type=secret,id=rhsm-user,target=/run/secrets/rhsm-user \
    --mount=type=secret,id=rhsm-pass,target=/run/secrets/rhsm-pass \
    subscription-manager register \
      --username="$(cat /run/secrets/rhsm-user)" \
      --password="$(cat /run/secrets/rhsm-pass)" && \
    dnf config-manager --set-enabled \
      rhocp-${USHIFT_VER}-for-rhel-9-$(uname -m)-rpms \
      fast-datapath-for-rhel-9-$(uname -m)-rpms && \
    dnf install -y \
      firewalld \
      microshift \
      microshift-olm \
      cloud-init \
      ansible-core \
      python3-pip \
      jq \
      curl && \
    subscription-manager unregister && \
    dnf clean all

# ── Python deps for identity-service and EDA ─────────────────────────
RUN pip3 install --no-cache-dir \
      flask==3.1.1 \
      pyjwt==2.10.1 \
      gunicorn==23.0.0 \
      kubernetes==32.0.1 \
      ansible-rulebook==1.1.1 \
      ansible-runner==2.4.0

# ── Skupper / RHSI runtime ────────────────────────────────────────────
# Copy skupper router binary + Python runtime from skupper-router image
COPY --from=registry.redhat.io/service-interconnect/skupper-router-rhel9:3.4.2 \
     /usr/sbin/skrouterd /usr/sbin/skrouterd
COPY --from=registry.redhat.io/service-interconnect/skupper-router-rhel9:3.4.2 \
     /usr/lib/skupper-router /usr/lib/skupper-router
COPY --from=registry.redhat.io/service-interconnect/skupper-router-rhel9:3.4.2 \
     /usr/lib64/python3.9 /usr/lib64/python3.9

# ── Ollama (local LLM for offline AI) ────────────────────────────────
RUN curl -fsSL https://ollama.com/install.sh | OLLAMA_INSTALL_DIR=/usr/local/bin sh && \
    mkdir -p /var/lib/ollama

# ── MicroShift configuration ─────────────────────────────────────────
COPY microshift/config/config.yaml /etc/microshift/config.yaml

# ── MicroShift auto-apply manifests (applied on every start) ─────────
RUN mkdir -p /etc/microshift/manifests
COPY microshift/manifests/ /etc/microshift/manifests/

# ── Identity service ──────────────────────────────────────────────────
RUN mkdir -p /opt/identity-service
COPY identity-service/app.py /opt/identity-service/app.py
COPY identity-service/templates/ /opt/identity-service/templates/

# ── Dashboard ─────────────────────────────────────────────────────────
RUN mkdir -p /opt/dashboard
COPY dashboard/app.py /opt/dashboard/app.py
COPY dashboard/templates/ /opt/dashboard/templates/
COPY dashboard/static/ /opt/dashboard/static/

# ── Ansible playbooks ─────────────────────────────────────────────────
RUN mkdir -p /opt/ansible
COPY ansible/ /opt/ansible/

# ── EDA rulebook ──────────────────────────────────────────────────────
COPY eda/rulebook.yml /opt/eda/rulebook.yml

# ── Skupper site config (baked in; token injected via cloud-init) ─────
RUN mkdir -p /etc/skupper
COPY skupper/site.yaml /etc/skupper/site.yaml
COPY skupper/connector.yaml /etc/skupper/connector.yaml

# ── Systemd services ──────────────────────────────────────────────────
COPY systemd/identity-service.service /etc/systemd/system/identity-service.service
COPY systemd/dashboard.service        /etc/systemd/system/dashboard.service
COPY systemd/skupper-init.service     /etc/systemd/system/skupper-init.service
COPY systemd/eda-server.service       /etc/systemd/system/eda-server.service
COPY systemd/ollama.service           /etc/systemd/system/ollama.service

# ── Enable services ───────────────────────────────────────────────────
RUN systemctl enable \
      microshift \
      firewalld \
      cloud-init-local \
      cloud-init \
      cloud-config \
      cloud-final \
      identity-service \
      dashboard \
      skupper-init \
      eda-server \
      ollama

# ── Firewall rules for MicroShift ────────────────────────────────────
RUN firewall-offline-cmd --add-port=6443/tcp && \
    firewall-offline-cmd --add-port=8080/tcp && \
    firewall-offline-cmd --add-port=8888/tcp && \
    firewall-offline-cmd --add-source=10.42.0.0/16 && \
    firewall-offline-cmd --add-source=169.254.169.1/32

# ── Post-quantum cryptography ─────────────────────────────────────────
# Enable ML-KEM (Kyber) hybrid key exchange — quantum-resistant TLS.
# Relevant for USSF/DoD: satellites have 10-15 year lifespans; harvest-now-
# decrypt-later attacks make PQC a current requirement, not a future one.
# RHEL 10 makes this the default; here we enable it explicitly on RHEL 9.
RUN update-crypto-policies --set DEFAULT:PQ

# ── Demo user ─────────────────────────────────────────────────────────
RUN useradd -m -G wheel demo && \
    echo "demo:redhat" | chpasswd

# ── Demo shell environment ────────────────────────────────────────────
# Auto-copy MicroShift kubeconfig, set oc alias, default to jtac-ops
COPY systemd/setup-demo-env.service /etc/systemd/system/setup-demo-env.service
RUN echo '#!/bin/bash' > /etc/profile.d/microshift-demo.sh && \
    echo 'export KUBECONFIG=/home/demo/kubeconfig' >> /etc/profile.d/microshift-demo.sh && \
    echo "alias oc='kubectl'" >> /etc/profile.d/microshift-demo.sh && \
    chmod +x /etc/profile.d/microshift-demo.sh
RUN systemctl enable setup-demo-env
