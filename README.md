# Hermes Agent All In One

An opinionated container built on the official [Hermes Agent](https://github.com/NousResearch/hermes-agent) image, with a small set of additional command-line tools and APIs. Hermes keeps its native gateway, supervision, and web dashboard; this image adds the utilities listed below.

## Bundled extras

- **Codex CLI** (`@openai/codex`)
- **Obsidian Headless Sync** (`obsidian-headless`)
- **Agent Browser** (`agent-browser`), Playwright, and Chromium
- **Google APIs for Python**: Google API client, authentication libraries, and HTTP support
- **System utilities**: `file`, `ffmpeg`, and `ripgrep` (`rg`)

Hermes' official image already provides its supported CLI, Node.js, git, and other runtime components. Hermes extras and integrations follow the pinned official image release.

## Railway deployment

The container uses the official Hermes image entrypoint and its native web dashboard. Attach a Railway volume mounted at **`/data`**. Existing deployments keep their current data paths:

- Hermes profile and configuration: `/data/.hermes`
- Workspaces: `/data/.hermes/workspace` (and any configured workspace paths under `/data`)
- Lazy installed Hermes packages: `/data/.hermes/lazy-packages`
- Runtime global npm updates: `/data/.hermes/npm-global` (its binaries take precedence over bundled tools, so `npm install -g obsidian-headless@latest` updates `ob` without root permissions)

The image sets `HOME=/data`, `HERMES_HOME=/data/.hermes`, and `HERMES_WRITE_SAFE_ROOT=/data`. It serves the native Hermes dashboard on port **8080** and provides `/api/status` for Railway health checks. Set a unique `HERMES_DASHBOARD_BASIC_AUTH_SECRET` along with the username and password so login sessions survive restarts.

Configure the native dashboard's shared Basic Auth with Railway variables:

- `HERMES_DASHBOARD_BASIC_AUTH_USERNAME`
- `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` (or `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`)
- `HERMES_DASHBOARD_BASIC_AUTH_SECRET`

For an existing deployment, replace the old `ADMIN_USERNAME` and `ADMIN_PASSWORD` variables with the Hermes variables above. Existing Hermes credentials and configuration remain on the `/data` volume. Basic Auth is one shared dashboard credential; use a trusted access boundary for the public dashboard URL.

The official image starts a fresh gateway in the state configured by `HERMES_GATEWAY_BOOTSTRAP_STATE`; for automatic first boot, set it to `running`. Hermes' own container docs describe the remaining supported gateway and provider configuration.

## Existing deployments and upgrades

This image retains the existing `/data` mount and `/data/.hermes` profile location. At boot, a small init hook checks pending named-profile delivery records and runs Hermes' config migration for the root profile and each live named profile before Hermes reconciles profiles or starts its supervised services. The upstream single-profile migration is disabled so it does not run twice. It does not move or rename profile/work directories.

Before an upgrade, take a consistent backup of the Railway volume. If the delivery check reports pending records, review the startup message before asking affected senders to retry; a retry starts a new agent turn. An unreadable profile ledger stops startup so the state can be reviewed safely.

## Continuous Obsidian sync

The bundled `ob` CLI can run continuously as an s6-supervised service alongside
Hermes. Set `OBSIDIAN_VAULT_PATH` to an absolute vault directory under `/data`,
for example `/data/.hermes/workspace/vault`. With this variable unset or empty,
the service stays disabled. One container syncs one configured vault.

The service uses the container's `HOME` and `XDG_CONFIG_HOME` without overriding
them. The image defaults to `HOME=/data` with `XDG_CONFIG_HOME` unset, so Obsidian
uses `/data/.config/obsidian-headless`. If `XDG_CONFIG_HOME` is set, Obsidian uses
`$XDG_CONFIG_HOME/obsidian-headless` instead. Keep that directory writable by
`hermes` and on persistent storage.

For existing Obsidian state under `/data`, startup repairs ownership of the
Obsidian directory and its config parent to `hermes`, preserving file modes.
This supports credentials and vault links created by older root-run containers.
It does not recursively change ownership of other applications' config files.

Existing login and vault links in that location are reused. For a new setup,
log in and link the vault once inside the running container as `hermes`:

```sh
/command/s6-setuidgid hermes ob login

/command/s6-setuidgid hermes ob sync-setup --vault "My Vault" \
  --path /data/.hermes/workspace/vault
```

Use an interactive terminal for login and any encryption-password prompt. An
active Obsidian Sync subscription is required. See the official
[Headless Sync documentation](https://obsidian.md/help/sync/headless).

After setup, set `OBSIDIAN_VAULT_PATH` and restart the container. At boot, the
inherited entrypoint starts `ob sync --continuous --path "$OBSIDIAN_VAULT_PATH"`
as `hermes`. The vault stays on the persistent volume, and the service preserves
the sync settings chosen during setup.

Sync output goes to container logs. s6 restarts the process after exits with a
three-second delay and signals it during container shutdown. Missing setup or
authentication failures are logged and retried without stopping Hermes. The
Hermes `/api/status` health check does not report Obsidian sync health. Remove
`OBSIDIAN_VAULT_PATH` and restart to disable sync.

This service requires the normal PID-1 entrypoint path; the upstream fallback
for containers launched under another init does not start s6 services.

## Managing bundled utilities

Python extras are declared and locked in [`aio-python/pyproject.toml`](aio-python/pyproject.toml) and [`aio-python/uv.lock`](aio-python/uv.lock). Node utilities are declared and locked in [`aio-npm/package.json`](aio-npm/package.json) and [`aio-npm/package-lock.json`](aio-npm/package-lock.json). The Docker build installs these locks into the Hermes runtime. Chromium is installed with Playwright.

Dependabot updates the Python and npm lockfiles weekly. Review those updates and redeploy to include them.

## Credits

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research
- This project builds on the [original Hermes Agent Railway template](https://github.com/praveen-ks-2001/hermes-agent-template).
