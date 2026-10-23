# Build context: repo root (see docker-compose.yml). services/main/ is the `main` package itself.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY sdk /opt/mycelium-sdk
RUN pip install --no-cache-dir /opt/mycelium-sdk
WORKDIR /srv
COPY services/main ./main
CMD ["python", "-m", "main"]
