# Build context: repo root (see docker-compose.yml). services/builder/ is the `builder` package itself.
# It never runs generated code: the supervisor verifies a build in a sealed container. git commits each build.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp/builder-home
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /tmp/builder-home && chmod 1777 /tmp/builder-home
COPY sdk /opt/mycelium-sdk
RUN pip install --no-cache-dir /opt/mycelium-sdk
WORKDIR /srv
COPY services/builder ./builder
CMD ["python", "-m", "builder"]
