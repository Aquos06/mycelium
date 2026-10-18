# Build context: repo root
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY sdk /opt/mycelium-sdk
RUN pip install --no-cache-dir /opt/mycelium-sdk httpx>=0.27
WORKDIR /srv
COPY services/telegram/telegram_bridge.py .
CMD ["python", "telegram_bridge.py"]
