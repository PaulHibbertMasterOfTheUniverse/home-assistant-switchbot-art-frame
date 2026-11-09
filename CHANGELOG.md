# 0.7.0-beta.1

- Private HA artwork gallery: save uploads/generated art, select previews and send to any configured destination; automation action included.
- Optional bin fan artwork, imported only on request.
- Optional original 31.5-inch Wi-Fi bin reminder: user-supplied calendar or Erewash UPRN, reminder weekday, 16:00 display and 19:30 restore/purge.
- Persist restoration intent across restarts; verify device-local notification removal before clearing it.
- Original-frame cache release/download checks, bounded retry and diagnostic stages; stored-picture Sync avoids altering static schedules.
- Retain public multi-frame routing, account-region handling and Frame 2 local controls.

# Changelog

## 0.6.0-beta.1 — 9 November 2026

First public beta, packaged independently from the development installation.

- Guided app-account sign-in, frame discovery and per-frame connection setup.
- Optional discard of cloud credentials after obtaining a local Bluetooth key.
- Multiple frame entries with isolated image tracking and explicit routing.
- Bundled dashboard for upload, generation preview, orientation, connection mode and confirmed oldest-picture replacement.
- Authenticated large-source preparation and private replaced-picture backups.
- Existing tested Frame2 local transport and original-frame cloud transport profiles, including improved31.5-inch colour conversion.
- Optional notification switch and opt-in example picture; retained local notification copy excluded from normal rotation.
- Own-account optional Cloudflare configuration.
- Synthetic tests, isolated Home Assistant API smoke tests, public-file checks and release hash manifest.

This beta does not claim every firmware, region, proxy or Frame2 size is supported. See README and docs/VALIDATION.md before installing.
