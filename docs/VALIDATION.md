# Release validation — 9 November 2026

## Real device evidence carried into this beta

The development build was physically tested with a 13.3-inch Frame 2 using local Bluetooth image uploads and stored-image selection, including Wi-Fi-blocked tests. Original-frame profiles cover 7.3,13.3 and31.5-inch sizes; their new uploads use SwitchBot cloud/Wi-Fi. The 31.5-inch orientation correction and improved colour rendering were confirmed on the physical screen. That does not establish support for every firmware, region, adapter or proxy.

## New public setup

A generic installation identity and app login discovered four supported frames across both generations. The public module retrieved a correctly sized per-frame Bluetooth key and read its cloud catalogue. No packet-capture template was needed. This read-only check used the EU account region. Other supported account regions select fixed hosts but have not been verified with regional accounts.

The new setup code was tested separately against installed Home Assistant2026.11.0 / Python3.14.2. Real Home Assistant API smoke tests exercise the setup forms, cloud-credential discard for a local entry, entry setup/unload, endpoint/action registration and bundled frontend registration. External calls in these lifecycle tests are mocked; they are not a substitute for a second household's fresh installation.

Controller regressions cover routing, frame isolation, local-slot retries, capacity confirmation, archive-before-delete, cloud-registration reconciliation, source preparation, orientation and colour conversion. JavaScript checks cover bounded previews, release of decoded images, large-file preparation on HA, and generated artwork superseding a selected file.

## Privacy

The publication tree was built by an allowlist from source and synthetic tests. Captures, accounts, real device identities, installation commands/backups, private image URLs and personal screenshots are excluded. A separate local comparison checks known private values before publishing. `tools/check_public.py` checks allowed file types, common secret patterns, private-address patterns and the sole approved photo's metadata. `tools/build_release.py` creates a deterministic file-hash manifest and packages only checked public files.

## Remaining beta limits

- The new guided setup has not yet been installed in a second household.
- Frame2 sizes other than13.3-inch are disabled.
- Original-frame new-image transfer is not local Bluetooth.
- Social-only and additional verification-code account flows are not implemented.
- Retained account login is required for automatic cloud reconnect; purely local entries need re-adding after a key-changing reset.
- Passive BLE advertisement forwarding is insufficient; active proxy compatibility needs hardware-specific testing.
- The browser large-image preparation test is not proof that every Android companion-app crash is resolved.
- Optional Cloudflare generation uses the user's account and current provider quotas.

The first public release is a beta, with these limits stated rather than presented as universal compatibility.
