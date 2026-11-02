# Aider for the builder (agents.yaml). FROM module-base: Python, the SDK and pytest for the module's tests.
# Aider gets a venv of its own, so its pinned dependencies never change the SDK's.
ARG BASE_IMAGE=mycelium/module-base:latest
FROM ${BASE_IMAGE}
USER root
RUN python -m venv /opt/aider && /opt/aider/bin/pip install --no-cache-dir aider-chat==0.86.2 \
 && ln -s /opt/aider/bin/aider /usr/local/bin/aider \
 && mkdir -p /work && chown module:module /work
COPY run.sh /usr/local/bin/run-agent
RUN chmod 755 /usr/local/bin/run-agent
USER module
ENV HOME=/home/module GIT_PYTHON_REFRESH=quiet
WORKDIR /work/module
CMD ["run-agent"]
