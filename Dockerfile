ARG HERMES_IMAGE=docker.io/nousresearch/hermes-agent:v2026.9.24
FROM ${HERMES_IMAGE}

USER root

# Keep the persistent layout used by existing Railway volumes. Hermes' native
# Docker image supplies the s6 entrypoint, gateway supervision, and dashboard.
ENV HOME=/data \
    HERMES_HOME=/data/.hermes \
    HERMES_WRITE_SAFE_ROOT=/data \
    HERMES_LAZY_INSTALL_TARGET=/data/.hermes/lazy-packages \
    HERMES_SKIP_CONFIG_MIGRATION=1 \
    HERMES_DASHBOARD=1 \
    HERMES_DASHBOARD_HOST=0.0.0.0 \
    HERMES_DASHBOARD_PORT=8080 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright

# Utilities not included in the official Hermes image.
RUN apt-get update && \
    apt-get install -y --no-install-recommends file ffmpeg ripgrep && \
    rm -rf /var/lib/apt/lists/*

# The migration helper covers root and each live profile. Running it after
# Hermes seeds the volume but before profile reconciliation keeps existing
# Railway data in place and prevents either Hermes service from reading an
# unmigrated config. Delivery preflight is read-only and may stop an unsafe
# upgrade when a profile ledger cannot be checked.
COPY migrate_hermes_configs.py check_pending_deliveries.py /app/
COPY docker/00-railway-volume-perms /etc/cont-init.d/00-railway-volume-perms
COPY docker/011-aio-preflight /etc/cont-init.d/011-aio-preflight
RUN chmod 0755 /etc/cont-init.d/00-railway-volume-perms /etc/cont-init.d/011-aio-preflight

# Add-on Python packages share the Hermes interpreter and are locked for its
# Python 3.13 runtime. Sync from uv.lock directly so artifact URLs and hashes
# from the lock are used instead of re-resolving versions through the index.
COPY aio-python/pyproject.toml aio-python/uv.lock /app/aio-python/
RUN VIRTUAL_ENV=/opt/hermes/.venv uv sync --project /app/aio-python \
        --active --locked --no-install-project --no-dev --inexact && \
    chown -R hermes:hermes /opt/hermes/.venv

# Codex CLI, Obsidian Headless Sync, and agent-browser.
COPY aio-npm/package.json aio-npm/package-lock.json /opt/aio-npm/
RUN npm ci --prefix /opt/aio-npm --omit=dev --no-audit --no-fund && \
    chown -R hermes:hermes /opt/aio-npm
ENV PATH=/opt/aio-npm/node_modules/.bin:/opt/hermes/bin:/opt/hermes/.venv/bin:${PATH}

# Chromium stays outside /data so Railway volume mounts cannot hide the browser binaries.
RUN mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" && \
    npx --prefix /opt/aio-npm playwright install chromium --only-shell && \
    chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"

# Keep upstream's /init dispatcher and CMD intact.
