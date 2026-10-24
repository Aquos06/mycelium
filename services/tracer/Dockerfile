# Build context: repo root
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY sdk /opt/mycelium-sdk
RUN pip install --no-cache-dir /opt/mycelium-sdk
WORKDIR /srv
COPY services/tracer/tracer.py .
CMD ["python", "tracer.py"]
