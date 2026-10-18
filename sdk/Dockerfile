# Base image every generated module builds FROM.
# Built by the supervisor on startup as mycelium/module-base:latest (and by CI).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODULE_DATA_DIR=/data MODULE_MANIFEST=/app/manifest.yaml

COPY . /opt/mycelium-sdk
RUN pip install --no-cache-dir /opt/mycelium-sdk pytest pytest-asyncio \
 && useradd --create-home --uid 10001 module \
 && mkdir -p /data /app && chown module:module /data /app

WORKDIR /app
USER module
