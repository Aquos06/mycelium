# Build context: repo root (see docker-compose.yml). The gateway alone: the app is its own image (frontend/Dockerfile).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY sdk /opt/mycelium-sdk
COPY services/web/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir /opt/mycelium-sdk -r /tmp/requirements.txt
WORKDIR /srv
COPY services/web ./web
EXPOSE 8080
CMD ["python", "-m", "web"]
