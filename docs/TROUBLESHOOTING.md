# Troubleshooting

## Setup cannot sign in

Use the app account login exactly, preserving password characters and email case. A store account is different. Apple/Google-only sign-in, challenges requiring a verification code, and additional account authentication flows are not implemented. Do not change security settings just to make this integration connect. A new app API or unsupported region may also need an integration update.

## Frame is not listed

The frame must be paired with the selected SwitchBot account. Supported identifiers are the original AI Art Frame and AI Art Frame 2; supported sizes are listed in the README. Shared-account permissions can differ from ownership. Unsupported models are not offered as a guessed destination.

## Bluetooth unavailable

Check HA's Bluetooth integration, connectable range and active connection capacity. A passive scanner or advertisement forwarder cannot carry the image stream. An actively connecting ESPHome Bluetooth proxy may be suitable, but image-transfer performance must be tested with that hardware. Generic Shelly BLE advertisement forwarding is not a guaranteed substitute. Keep the phone app disconnected while testing HA.

Bluetooth-only never silently uploads through SwitchBot. An original frame cannot accept a new local picture through the currently established protocol; use Wi-Fi mode if you want new uploads on that generation.

## Image upside down or cropped

Set portrait/landscape and Rotate 180° for that destination before sending. These choices are saved separately per frame. The preview is a centre crop, so prepare a matching composition if the subject is near an edge. Rotating a setting does not rewrite images already stored on the frame.

## Washed-out colour on a 31.5-inch original

This profile uses the recovered app saturation/contrast and calibrated six-ink Stucki conversion. It was physically compared with the older generic converter and produced stronger colour. E-paper still has a limited palette; it cannot reproduce every screen colour. Other frame profiles retain their previously tested conversion paths.

## Carpet / incomplete / mixed picture

Allow the full e-paper refresh to settle. A successful cloud command or storage report is not proof of the physical screen. Record the exact frame generation, size, firmware, connection mode and error/status. Avoid multiple overlapping sends from the app and HA. Update firmware through the vendor app if directed by the vendor; do not factory-reset merely because an upload is slow. The tested implementation transfers the whole native buffer and verifies transfer completion, but untested firmware can behave differently.

## Full album or error191

A full cloud album returned code191 on one tested original frame even when the device list differed. The integration checks both lists and offers a confirmed, targeted oldest-picture replacement. A private original JPEG is saved before freeing a cloud entry. An uncertain network timeout remains a pending registration until reconciled; blindly retrying can create duplicates.

The advanced reconcile action must only confirm a rejection when you have established that no cloud registration was created. It is not a general “ignore error” button.

## Factory reset / account password change

After pairing the same frame again in the SwitchBot app, use **Reconnect after reset** if cloud login was retained. Bluetooth keys may have changed. Purely local entries that discarded cloud sign-in need removal and re-addition through this integration's setup flow to obtain the new key. Removing an entry does not delete artwork from the frame. The image ledger is keyed by device identity; after a real factory reset, verify stored pictures before relying on an old notification/playlist reservation.

If the account password changed, remove and re-add the integration entry with the new app login. The current public beta does not yet provide an in-place account reauthentication screen.

## Android photo picker

The card streams large originals to HA and only renders a bounded preview on the phone. A 12 MiB / 48 MP source passed the browser preparation test. A companion-app process crash cannot be ruled out by that browser test alone; include phone/app versions when reporting a repeatable Android restart.
