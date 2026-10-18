# Builder sandbox: Claude Agent SDK + mycelium SDK. Only modules/, template/, specs/ and builds/ are mounted.
# Runs as your host UID (see docker-compose.yml) so generated files are owned by you.
# Build context: repo root
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MYCELIUM_ROOT=/workspace HOME=/tmp/builder-home
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY sdk /opt/mycelium-sdk
COPY builder/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir /opt/mycelium-sdk -r /tmp/requirements.txt \
 && mkdir -p /tmp/builder-home && chmod 1777 /tmp/builder-home
WORKDIR /workspace
COPY scripts/new_module.py /workspace/scripts/new_module.py
COPY builder/build.py /workspace/builder/build.py
ENTRYPOINT ["python", "/workspace/builder/build.py"]
