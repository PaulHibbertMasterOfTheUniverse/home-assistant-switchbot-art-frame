# Privacy and data flow

## Bluetooth only

Setup signs into SwitchBot and reads the account's frame list and the selected frame's communication key. It does not upload a picture or modify the frame during setup. If you decline retained cloud login, the finished entry keeps the frame identity/key and discards the cloud account credentials and token.

For the supported 13.3-inch Frame 2, photo preparation and transfer then run in Home Assistant and over Bluetooth. The card's Bluetooth-only policy does not silently fall back to the cloud. Existing normal pictures and a retained notification picture can be selected locally.

## Wi-Fi and hybrid

Wi-Fi mode uses SwitchBot's internet services. New image JPEG/thumbnail/display data are uploaded to SwitchBot's storage and registered in its cloud album, then downloaded by the frame. This is not a LAN-only API. Hybrid mode permits cloud fallback before an operation starts if Bluetooth is unavailable. The card displays the selected connection policy.

Cloud connection data is stored in the user's HA config entry, not the dashboard JavaScript. The account's regional SwitchBot service is selected from its user-info response. Setup and runtime only use fixed SwitchBot HTTPS hostnames and validated image-upload destinations.

## Generation

Optional image generation sends the text prompt to Cloudflare using the user's own account/token. Generation makes a preview; it does not send that preview to the frame until the user requests delivery. A Bluetooth-only frame does not make Cloudflare generation local.

## Images and backups

Original uploads are streamed to Home Assistant for resizing. Normal image preparation uses memory; replaced cloud-image backups are intentionally retained under `frame_art_archive` in the HA configuration folder. They are outside the public `www` directory and downloadable only through an authenticated administrator endpoint.

Endpoints for upload, preparation, generation and backup require an authenticated Home Assistant administrator. No public image-hosting URL is required for this release. The package contains no user account, captured session, real device identifier or home address. The sole personal-image exception is the opt-in baby-asleep example supplied with the publisher's permission; its JPEG metadata has been removed.

Do not post passwords, session tokens, communication keys, account files or unredacted HA backups in issues or support chats.

Gallery files and pending bin-restoration records stay in your own HA configuration. This release includes no household configuration, collection address/UPRN, real frame ID or saved session. The optional Erewash source sends the UPRN you configure to the council; a calendar source queries your chosen HA calendar. Bin delivery for the original frame sends artwork through SwitchBot cloud.
