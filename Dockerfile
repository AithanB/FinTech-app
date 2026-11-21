FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS agent-runtime

RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 tzdata && rm -rf /var/lib/apt/lists/*
COPY scripts/build_agent_runtime.py scripts/agent_bootstrap.py /build/
RUN python /build/build_agent_runtime.py /opt/agent-runtime
RUN dpkg-query -W > /opt/agent-runtime-packages.txt

FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=agent-runtime /opt/agent-runtime /opt/agent-runtime
COPY --from=agent-runtime /usr/share/doc /opt/agent-runtime-licenses
COPY --from=agent-runtime /opt/agent-runtime-packages.txt /opt/agent-runtime-packages.txt
# The trusted evaluator owns all source/data. The agent sees only its jail.
RUN chmod 700 /app && find /app/tests/fixtures -path '*/private/*' -type f -exec chmod 600 {} + \
    && find /app/tests/fixtures -path '*/public/*' -type f -exec chmod 444 {} + \
    && chmod -R go-rwx /app/evaluator \
    && find /app/episodes/train /app/episodes/dev -type f -exec chmod 444 {} +

CMD ["python", "-m", "audit_env"]
