ARG BASE_IMAGE=mycelium/module-base:latest
FROM ${BASE_IMAGE}
COPY --chown=module:module requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --user -r /app/requirements.txt
COPY --chown=module:module . /app
CMD ["python", "-m", "app.main"]
