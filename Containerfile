FROM registry.redhat.io/rhel10/rhel-bootc:10.2
ARG USHIFT_VER=4.22

# ── MicroShift repos ──────────────────────────────────────────────────
RUN dnf config-manager --set-enabled \
      rhocp-${USHIFT_VER}-for-rhel-10-$(uname -m)-rpms \
      fast-datapath-for-rhel-10-$(uname -m)-rpms

# ── Base packages ─────────────────────────────────────────────────────
RUN dnf install -y \
      firewalld \
      microshift \
      microshift-olm \
      cloud-init \
      ansible-core \
      python3-pip \
      jq \
      curl && \
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
COPY --from=registry.redhat.io/service-interconnect/skupper-router-rhel9:latest \
     /usr/sbin/skrouterd /usr/sbin/skrouterd
COPY --from=registry.redhat.io/service-interconnect/skupper-router-rhel9:latest \
     /usr/lib/skupper-router /usr/lib/skupper-router
COPY --from=registry.redhat.io/service-interconnect/skupper-router-rhel9:latest \
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

# ── Demo user ─────────────────────────────────────────────────────────
RUN useradd -m -G wheel demo && \
    echo "demo:redhat" | chpasswd
