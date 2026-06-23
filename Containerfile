FROM registry.access.redhat.com/ubi9/python-311:latest

USER 0

RUN dnf install -y --allowerasing git curl jq golang && dnf clean all && \
    curl -sL -o /tmp/rg.tar.gz "https://github.com/BurntSushi/ripgrep/releases/latest/download/ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz" && \
    tar xzf /tmp/rg.tar.gz -C /tmp && \
    cp /tmp/ripgrep-*/rg /usr/local/bin/ && \
    rm -rf /tmp/rg.tar.gz /tmp/ripgrep-*

RUN curl -fsSL https://cli.github.com/packages/rpm/gh-cli.repo \
      > /etc/yum.repos.d/gh-cli.repo && \
    dnf install -y gh && dnf clean all

RUN OPENSHELL_VERSION=v0.0.62 \
    curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh

RUN cd /tmp && \
    curl -sL -o opencode.tar.gz \
    "https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux-x64.tar.gz" && \
    tar xzf opencode.tar.gz && \
    mv opencode /usr/local/bin/opencode && \
    chmod +x /usr/local/bin/opencode && \
    rm -f opencode.tar.gz && \
    opencode --version

COPY orchestrator/requirements.txt /app/orchestrator/requirements.txt
RUN pip install --no-cache-dir -r /app/orchestrator/requirements.txt

COPY config/ /app/config/
COPY orchestrator/ /app/orchestrator/
COPY policies/ /app/policies/
COPY .opencode/agents/ /app/.opencode/agents/
COPY .opencode/skills/ /app/.opencode/skills/
COPY .opencode/plugins/ /app/.opencode/plugins/
COPY opencode.json /app/opencode.json
COPY AGENTS.md /app/AGENTS.md

WORKDIR /app
RUN mkdir -p orchestrator/state orchestrator/logs runs .opencode \
    /opt/app-root/src/.local/share/opencode/log \
    /opt/app-root/src/.config/opencode && \
    chmod -R 777 /opt/app-root/src/.local /opt/app-root/src/.config && \
    git config --system user.email "issue-fix-agent@bot.local" && \
    git config --system user.name "issue-fix-agent"

ENV PYTHONUNBUFFERED=1

USER 1001

CMD ["python", "-m", "orchestrator.watcher", "--loop"]
