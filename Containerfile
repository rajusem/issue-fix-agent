FROM registry.access.redhat.com/ubi9/python-311:latest

USER 0

RUN dnf install -y git curl jq && dnf clean all

RUN curl -fsSL https://cli.github.com/packages/rpm/gh-cli.repo \
      > /etc/yum.repos.d/gh-cli.repo && \
    dnf install -y gh && dnf clean all

RUN OPENSHELL_VERSION=v0.0.62 \
    curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh

RUN curl -fsSL https://opencode.ai/install | sh

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
RUN mkdir -p orchestrator/state orchestrator/logs runs .opencode

ENV PYTHONUNBUFFERED=1

USER 1001

CMD ["python", "-m", "orchestrator.watcher", "--loop"]
