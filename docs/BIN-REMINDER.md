# Optional bin-day reminder

**Tested device: original AI Art Frame, 31.5-inch, Wi-Fi/cloud mode.** This reminder currently rejects other models/sizes instead of pretending they support this cleanup protocol. All supported frames can still use the gallery and its artwork. Frame 2's existing local notification-switch feature remains available separately.

The reminder checks the following morning's collection on your chosen weekday at **16:00**, displays blue/black/no-collection artwork, then at **19:30** restores the exact previous picture and removes the notification's device-local copy. The cloud album entry and HA example images are retained for reuse. One free cloud-album slot is needed on first use; existing photos are never silently deleted to make room.

## Install and configure

1. Install/update the main integration and add your frame first.
2. From the release ZIP, also copy the `frame_bin_reminder` folder from `extras/` into HA's `custom_components/` folder. This optional folder is installed manually alongside the main HACS integration.
3. Set portrait/landscape and Rotate 180° correctly for the destination in the dashboard. Bundled bin artwork is fitted with white padding so the headings and quotes remain visible.
4. Add ONE of the following blocks to `configuration.yaml`, using your own frame ID. No example contains a real property reference. Restart HA after configuration validation.

### Any council: your collection calendar

Use a dedicated, authoritative collection calendar in HA that includes holiday changes. The calendar integration must support `calendar.get_events`. Do not use an unchecked weekly repeating reminder and expect it to detect Christmas changes.

```yaml
frame_bin_reminder:
  frame_id: YOUR_FRAME_ID
  source: calendar
  calendar_entity: calendar.bin_collections
  reminder_weekday: 1  # Monday=0, Tuesday=1, ... Sunday=6
  blue_keywords: [blue, recycling]
  black_keywords: [black, general waste, domestic waste]
  enabled: false
```

The calendar is queried for the following day. A successfully fetched empty day means no collection **in that calendar**; missing/unavailable responses or ambiguous/both-bin events produce an error rather than a guessed picture. Adjust keywords to match your actual event titles. An incomplete calendar cannot prove a council cancellation.

### Erewash's official checker

```yaml
frame_bin_reminder:
  frame_id: YOUR_FRAME_ID
  source: erewash
  uprn: !secret bin_property_uprn
  reminder_weekday: 1
  enabled: false
```

Set `bin_property_uprn` privately in `secrets.yaml` to your own property's official UPRN, quoted as a string. The postcode/house-number lookup is not performed by this integration. The council feed and holiday rules are Erewash-specific; this is not a universal council scraper. Unpublished Christmas/New Year dates are treated as unknown, not cancellations. The calendar route above is available for other councils.

## Test, then enable

Run in **Developer tools → Actions**:

```yaml
action: frame_bin_reminder.test_picture
data:
  kind: blue  # blue, black, or none
```

This uses the real production delivery path and saves your previous picture for automatic cleanup after ten minutes. To test the restore/cleanup immediately:

```yaml
action: frame_bin_reminder.restore
```

Check the physical screen as well as HA's status. Device/cloud status can lag the screen by minutes. Completed cleanup requires the saved original selected and the temporary slot absent from the storage list. Failed cleanup retains its record and retries on the next minute or after restart; it does not report success merely because a command was accepted.

After a successful test:

```yaml
action: frame_bin_reminder.set_enabled
data:
  enabled: true
```

Status is `sensor.frame_bin_reminder_YOUR_FRAME_ID`. `refresh` checks tomorrow's collection without changing the frame. `display_picture` is a manual display with cleanup at the next configured reminder weekday at 19:30; it preserves an existing restoration record. `restore` ends it early. `set_enabled: false` stops new scheduled reminders but **does not cancel pending cleanup**. The optional component currently controls one destination per HA installation; its underlying frame controller/gallery still support multiple frames.

## Timing and recovery

The 16:00 trigger starts an operation, not an instantaneous screen refresh. Original-frame Wi-Fi commands may take several minutes. The uploader confirms cache release before downloading changed artwork, retries a missed download once, confirms storage, waits for settling, then selects. It never creates repeated album entries as a retry strategy. Cleanup is restart-safe and checks what is already complete before repeating work. Verify the first full unattended scheduled cycle in your own home.

The example fan artwork is optional and separately described in [artwork terms](../custom_components/switchbot_frame_control/examples/README.md). Keep your own calendar, UPRN, keys and backups private. This feature requires SwitchBot cloud access; do not advertise it as fully local.

After configuring and restarting, select that frame in the Art Frame dashboard and use **Enable bin reminders** or **Disable bin reminders**. The section appears only for the configured reminder frame. Reminders default to off. Turning them off does not cancel cleanup of an already displayed reminder.
