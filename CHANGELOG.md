# Changelog

## Image transition

- The image now uses the official Hermes Agent container entrypoint and native dashboard.
- Existing Railway volumes continue to use `/data` with Hermes data under `/data/.hermes`.
- The former custom web server, launcher, admin screens, and backup interface have been removed.
- A narrow startup hook checks legacy named-profile delivery records and migrates each live Hermes profile before profile reconciliation.
- The AIO Python dependency lock now targets Python 3.13, matching the pinned Hermes image.

See the [Hermes Agent release notes](https://github.com/NousResearch/hermes-agent/releases) for changes in the underlying agent.
