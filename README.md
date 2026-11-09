# SwitchBot Art Frame Control for Home Assistant

Upload pictures, save a private artwork gallery in Home Assistant, create artwork, control multiple frames and show notification or bin-day pictures from automations.

**Public beta.** The device controls have been tested on real frames. Guided setup is new in this release. This is an independent custom integration, not an official SwitchBot integration.

## What works locally?

| Frame | New picture upload | Select pictures already stored | Supported sizes |
| --- | --- | --- | --- |
| AI Art Frame 2 | **Local Bluetooth** in Bluetooth-only mode | Local Bluetooth | 13.3-inch |
| Original AI Art Frame | **SwitchBot cloud and frame Wi-Fi required** | Bluetooth, or cloud in Wi-Fi mode | 7.3, 13.3 and 31.5-inch profiles |

The original frame's upload limitation is explicit: Wi-Fi mode is cloud control, not a local network API. Other Frame 2 sizes are not enabled because their display format has not been validated. Regional cloud hosts are selected from your account; only the EU host has been tested on hardware so far.

Frame 2 needs an initial SwitchBot account connection to obtain its Bluetooth key. After that, Bluetooth-only picture delivery does not contact SwitchBot. You can choose not to retain your cloud sign-in during setup. Optional AI generation uses Cloudflare and requires internet access; uploading an existing photo does not require AI generation.

## Install

This first beta targets **Home Assistant 2026.11.0 or newer**. Older releases are not covered by its setup validation.

1. Download the release ZIP and extract it.
2. Copy `custom_components/switchbot_frame_control` into your Home Assistant configuration directory's `custom_components` folder. Keep that exact folder name.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration**, search **SwitchBot Frame Control**, and sign in using your **SwitchBot app** email and password. This is not your SwitchBot online-shop account or an OpenAPI token.
5. Choose a frame, its exact screen size, and a connection mode. Repeat Add integration for additional frames. No packet capture or inspection certificate is needed.
6. On a dashboard, add a **Manual** card with:

```yaml
type: custom:frame-upload-card
```

The integration serves and registers its dashboard JavaScript automatically. If you used an older development copy, remove its old manual `frame-upload-card.js` resource and refresh the browser before testing the new card.

The repository follows the custom-integration layout used by HACS and the Home Assistant Marketplace. It is **not claimed to be included in either catalog**. Manual installation above remains available. If your installation supports custom GitHub integration repositories, use this repository URL and choose the integration type.

## First picture

Choose the destination, set portrait or landscape and rotate 180° if needed, then upload a JPEG, PNG or WebP. Home Assistant prepares large source images before the phone renders its preview (up to 64 MiB and 80 megapixels). Review the centre crop, then press **Send to frame**. A 31.5-inch picture needs additional colour-processing time.

If the frame or its cloud album is full, the dashboard asks before replacing the oldest eligible picture. If a cloud entry must be removed, it first saves a private JPEG backup in Home Assistant. **Download last replaced picture** prepares an explicit **Save backup JPEG** link. The tracked notification picture is protected from oldest-picture replacement.

## Private Home Assistant gallery

The dashboard now includes **Home Assistant artwork gallery**. Upload or generate a picture, give it a name, and press **Save current picture to gallery**. Select a saved picture and press **Send to frame**. The gallery is shared across your configured frames; sending uses the selected destination and its own orientation.

**Add bin artwork** imports the optional blue-bin, black-bin and no-collection pictures. Nothing is sent automatically. Each gallery item shows its ID for automations. Gallery pictures stay in your private HA configuration folder, outside public `www` hosting. Delivery still follows the destination's connection mode: gallery storage does not turn original-frame Wi-Fi uploads into a local network API.

See [gallery actions](docs/GALLERY.md) and the optional [bin-day reminder setup](docs/BIN-REMINDER.md). The bin reminder restores the previous picture and verifies removal of its temporary device copy; it does not leave the bin in normal rotation.

## Notification picture / “baby asleep” example

You can choose an existing Home Assistant switch or toggle during setup. An `input_boolean` helper works well. Select **Use example image** to use the optional “I AM ASLEEP” picture, or enter your own image's path inside your HA configuration folder. The example is opt-in, never displayed automatically during installation.

When the chosen switch turns on, the integration shows the notification picture. When it turns off, normal stored artwork resumes and excludes the tracked notification image. In local Bluetooth operation, one notification copy is retained and reused; **it is not deleted after every notification**. This prevents repeated uploads and duplicates. New artwork can override an active notification after confirmation in the dashboard.

For Alexa or Google Home, expose a suitable Home Assistant helper through your existing supported voice-assistant setup, then have your routine turn that helper on/off. This project does not supply Alexa/Google account linking or a free substitute for a paid remote-access service.

## Optional AI pictures

Open this integration's **Configure** options for the destination frame and enter your own Cloudflare account ID and Workers AI token. The token needs Workers AI execution permission. Press **Generate picture**, review the preview, then send it separately.

The configured model is FLUX.1 Schnell. Cloudflare's free allocation, model availability and rate limits are controlled by Cloudflare and can change. This integration does not enable a paid plan or promise unlimited free generation.

## Bluetooth requirements

Home Assistant needs a working connectable Bluetooth adapter or a proxy that supports **active GATT connections**. Seeing an advertisement is not sufficient for image transfer. A Shelly device relaying BLE advertisements is not automatically a compatible image-upload proxy. Close the SwitchBot app if it holds the frame's Bluetooth connection. See [connection and troubleshooting notes](docs/TROUBLESHOOTING.md).

## Account and privacy

App email/password sign-in is supported by the setup path. Social-only sign-in and verification-code challenges are not implemented; do not disable account protections to follow these instructions. A failed login leaves the flow open with an error.

If you retain cloud sign-in, HA stores the account connection in its configuration entry so it can reconnect or use Wi-Fi mode. Bluetooth keys are also private HA configuration. Keep HA backups private. No developer server or analytics is included. See [privacy and data flow](docs/PRIVACY.md).

## More

- [Actions, automations and multiple frames](docs/AUTOMATIONS.md)
- [Troubleshooting and known limitations](docs/TROUBLESHOOTING.md)
- [Help prompt for a new ChatGPT chat](docs/CHATGPT-HELP-PROMPT.md)
- [Release validation](docs/VALIDATION.md)
- [Contributing](CONTRIBUTING.md)

Source code is MIT licensed, with required third-party notices. The optional example photo has separate terms in `custom_components/switchbot_frame_control/examples/README.md`.
