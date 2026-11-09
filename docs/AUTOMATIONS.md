# Actions and automations

Every frame has its own configuration entry, image tracking, operation lock, saved orientation and status sensor. Select the destination in the dashboard. Adding one frame does not pair or alter another.

The setup flow generates a stable `frame_id` from that frame's device identity. Find your exact ID in the authenticated frame-list endpoint or in the selected frame's status sensor attributes. Replace `YOUR_FRAME_ID` below with that ID. Never copy someone else's device identity or Bluetooth key.

Show the configured notification:

```yaml
action: switchbot_frame_control.show_baby
data:
  frame_id: YOUR_FRAME_ID
```

Restore normal artwork after turning the configured notification switch off:

```yaml
action: switchbot_frame_control.restore_normal
data:
  frame_id: YOUR_FRAME_ID
```

Other actions:

| Action | Purpose |
| --- | --- |
| `set_connection_mode` | Set `mode: local`, `hybrid`, or `wifi` explicitly |
| `select_image` | Select an existing stored image by `index` |
| `repair_connection` | Explicit online reconnect using retained credentials |
| `backup_current_picture` | Back up the selected original-frame cloud JPEG privately |
| `reconcile_cloud_registration` | Advanced recovery of an uncertain registration |

With multiple frames, include `frame_id` explicitly. Omitted or unknown destinations are rejected rather than sent to an arbitrary frame.

For automatic notification behaviour, selecting the switch in setup is sufficient: its on/off changes are observed by the integration. You do not need a second automation that repeatedly uploads the same file. In local operation the notification is retained once and excluded from the normal playlist.

To use your own picture, save it inside the HA configuration folder and configure its relative path, for example `frame-images/notification.jpg`. Keep personal photos outside `www` unless you intentionally want public hosting. The included example can be selected during setup without copying files.
