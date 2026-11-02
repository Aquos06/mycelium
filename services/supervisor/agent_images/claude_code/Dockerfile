# Claude Code for the builder (agents.yaml). FROM module-base: Python, the SDK and pytest for the module's tests.
ARG BASE_IMAGE=mycelium/module-base:latest
FROM node:22-bookworm-slim AS node
FROM ${BASE_IMAGE}
USER root
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && npm install -g @anthropic-ai/claude-code@2.1.296 && npm cache clean --force \
 && mkdir -p /work && chown module:module /work
COPY run.sh /usr/local/bin/run-agent
RUN chmod 755 /usr/local/bin/run-agent
USER module
ENV HOME=/home/module
WORKDIR /work/module
CMD ["run-agent"]
