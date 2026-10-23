# Build context: repo root (see docker-compose.yml). services/memory/ is the `memory` package itself.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY sdk /opt/mycelium-sdk
COPY services/memory/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir /opt/mycelium-sdk -r /tmp/requirements.txt
WORKDIR /srv
COPY services/memory ./memory
CMD ["python", "-m", "memory"]
