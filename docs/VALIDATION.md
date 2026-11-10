# Release validation — 10 November 2026

## Real device evidence carried into this beta

The development build was physically tested with a 13.3-inch Frame 2 using local Bluetooth image uploads and stored-image selection, including Wi-Fi-blocked tests. Original-frame profiles cover 7.3,13.3 and31.5-inch sizes; their new uploads use SwitchBot cloud/Wi-Fi. The 31.5-inch orientation correction and improved colour rendering were confirmed on the physical screen. That does not establish support for every firmware, region, adapter or proxy.

## New public setup

A generic installation identity and app login discovered four supported frames across both generations. The public module retrieved a correctly sized per-frame Bluetooth key and read its cloud catalogue. No packet-capture template was needed. This read-only check used the EU account region. Other supported account regions select fixed hosts but have not been verified with regional accounts.

The new setup code was tested separately against installed Home Assistant2026.11.0 / Python3.14.2. Real Home Assistant API smoke tests exercise the setup forms, cloud-credential discard for a local entry, entry setup/unload, endpoint/action registration and bundled frontend registration. External calls in these lifecycle tests are mocked; they are not a substitute for a second household's fresh installation.

Controller regressions cover routing, frame isolation, local-slot retries, capacity confirmation, archive-before-delete, cloud-registration reconciliation, source preparation, orientation and colour conversion. JavaScript checks cover bounded previews, release of decoded images, large-file preparation on HA, and generated artwork superseding a selected file.

## Privacy

The publication tree was built by an allowlist from source and synthetic tests. Captures, accounts, real device identities, installation commands/backups, private image URLs and personal screenshots are excluded. A separate local comparison checks known private values before publishing. `tools/check_public.py` checks allowed file types, common secret patterns, private-address patterns and approved example images' metadata. `tools/build_release.py` creates a deterministic file-hash manifest and packages only checked public files.

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


## 0.7.0-beta.1 gallery and bin reminder

288 Python tests passed against Home Assistant 2026.11.0, including authenticated gallery setup, private persistence, explicit destination routing, opt-in artwork import, reusable calendar configuration, ambiguous-event handling, cache release/download sequencing, restoration guards and retry persistence. The two JavaScript image preparation/memory regression suites and card syntax check also passed. Public-file allowlisting, known-value privacy scanning and image metadata checks cover the final archive.

The production blue-bin send was physically confirmed complete and correctly oriented. Its production restore selected the previous photo and confirmed the notification absent from device-local storage, preserving the nine normal images and cloud album. Cleanup required its automatic retry. The corrected black-bin artwork was physically confirmed too. The public selection wait is extended to cover the delayed selection report observed in the live blue-bin test. The public calendar adapter, portable artwork preparation and first install on another household are software-tested; they have not been claimed as separately hardware-tested. A complete unattended weekday schedule still needs observing on the installer's own frame. Current bin reminder hardware scope is original 31.5-inch Wi-Fi/cloud only.

The optional component is in `extras/frame_bin_reminder` to preserve one main integration under `custom_components/` for HACS. Copy that extra folder manually as documented. No live Home Assistant configuration or restart was performed while packaging this release.

The 10 November public package also includes persisted same-slot replacement recovery and saved-layout revision guards from the live repair. Dedicated regression tests cover delayed release, restart resumption, duplicate prevention and stale browser layout. Dashboard tests cover the optional bin reminder enable/disable control. The public package itself has not replaced the household development installation.
