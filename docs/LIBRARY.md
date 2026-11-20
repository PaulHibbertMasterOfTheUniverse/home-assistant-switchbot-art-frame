# Upload-first private library (optional beta)

Supported profile: **original 31.5-inch frame, Wi-Fi/cloud mode**. This does not change Frame 2 Bluetooth transport, or claim local-only operation on the original frame. The mode is off by default, selected explicitly for each frame, and survives restarts.

The normal uploader is unchanged unless you opt in. This mode confirms that the new picture is stored and selected before it archives and removes the previous picture. It requires at least one spare slot in both the device and cloud catalogue; it never pre-deletes to make room. Current firmware/profile capacity is treated as ten entries. A pending cleanup does not reserve otherwise available slots.

## Enable for a frame

Back up your Home Assistant configuration first. In **Developer tools → Actions**, call:

```yaml
action: switchbot_frame_control.backup_library
data:
  frame_id: YOUR_FRAME_ID
```

This downloads the available cloud JPEG originals into the private HA gallery without changing the frame. These are the prepared images held by SwitchBot, not necessarily the original camera files. A device-only image without a verifiable original stops activation; the tool does not erase it. Check/download your gallery backups before proceeding.

Then explicitly enable:

```yaml
action: switchbot_frame_control.set_library_mode
data:
  frame_id: YOUR_FRAME_ID
  enabled: true
  retain_indices: []
```

Enabling performs another verified backup. **On subsequent successful sends, eligible previous pictures will be removed from frame and cloud storage after a verified private backup.** This is the opt-in to that behaviour. Add any additional slot numbers you want to retain to `retain_indices`. This list replaces the explicit retention list exactly; automatic notification and restoration protections remain independent. Existing normal-playlist, notification and bin-reminder restore references remain protected automatically.

This release does **not** empty existing collections on first run. The separate first-run migration/restore-from-gallery workflow remains unfinished and is not enabled. If the frame is already full, keep your verified backups and free a slot yourself using the app; no automated bootstrap deletion is provided.

Use the dashboard or `frame_art_gallery.send_image` normally after enabling. Upload acceptance, stored-and-selected confirmation and physical screen verification are distinct: the integration cannot see the actual screen.

## Cleanup and recovery

Cleanup intentions are saved independently in a durable queue before later uploads can replace the active delivery record. A stuck/paused cleanup does not block a different send while fresh device and cloud observations show spare space. Polling waits release the per-frame lock; commands and state transitions remain serialized. Genuine uncertain registration/delivery and full capacity still stop a new upload.

Cleanup checks the old picture's identity and recoverable backup again, and refuses to remove the current selection or a notification/restore reference. Lost replies and a restart can be reconciled against the current catalogue/storage. One failed queue item does not discard another. Cleanup does not delete the gallery originals.

Inspect with `switchbot_frame_control.inspect_library` and the explicit `frame_id`. It returns capacity, protected indices, delivery state and sanitized cleanup summaries. To resume a bounded cleanup retry, call `switchbot_frame_control.retry_library_cleanup`. An uncertain existing delivery can be resumed with `switchbot_frame_control.resume_library_delivery`; do not keep re-registering pictures.

Disable using `set_library_mode` with `enabled: false` after delivery and cleanup have finished. This does not re-upload removed pictures or undo backups. Archived transports can be sent from the private gallery only to their original frame and matching layout; otherwise review/convert the downloaded artwork first to avoid applying orientation twice.

## Validation limits

The installed development controller recovered an already-completed stuck cleanup on a real 31.5-inch device after restart, preserving its current selection and protected restore pictures. The public port has synthetic delivery, concurrency, persistence, recovery and lifecycle tests. A new end-to-end physical upload was not performed for this port. See [validation](VALIDATION.md).

## Background delivery in 0.7.2

The normal upload returns `accepted: true, pending: true` after saving the exact received source privately. Encoding, asset upload, registration and device waits run in a per-frame background task. This applies only to opted-in library mode. A different source is rejected while delivery is pending; resending the same source observes its existing identity without creating another registration.

Budgets are persisted across restart: up to two wake/download attempts and two selections, individual remote timeouts and a ten-minute delivery deadline. The frame is allowed to settle after waking. Lost replies are checked against fresh device state before a retry. An uncertain registration is never blindly repeated. A terminal error requires inspection/reconciliation; resending does not reset the budgets.

The animated bar deliberately has no invented percentage while the device reports no numeric progress. Completion means device-reported stored and selected, not physical screen inspection. Cleanup runs separately after confirmation. Delayed device membership updates can leave a cleanup warning even after cloud deletion; this is not a failed delivery and does not block another send while capacity is available.
