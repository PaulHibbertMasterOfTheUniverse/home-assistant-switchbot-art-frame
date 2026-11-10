# Private artwork gallery

Available automatically after updating the main integration to 0.7.0-beta.1 and refreshing the dashboard. No additional integration or public image hosting is required.

1. Upload or generate a picture in the dashboard.
2. Enter a name under **Home Assistant artwork gallery** and press **Save current picture to gallery**.
3. To reuse it, select the gallery thumbnail, choose the destination and orientation, then **Send to frame**.
4. **Add bin artwork** imports the three optional example artworks. It never displays them automatically.

The card shows each artwork's stable `art_…` ID. Re-saving identical prepared bytes reuses that ID. Automations can send a saved image directly:

```yaml
action: frame_art_gallery.send_image
data:
  frame_id: YOUR_FRAME_ID
  image_id: YOUR_GALLERY_IMAGE_ID
```

This action uses the destination's saved portrait/landscape and 180° setting. If the notification picture is active, it rejects a replacement unless you explicitly add `override_baby: true`. It uses the same uploader and connection mode as the dashboard.

Images and `index.json` are saved under `frame_art_gallery/` inside your HA configuration directory. Back up this directory privately. The gallery HTTP endpoints require an authenticated HA administrator; pictures are not put in `www`, exposed on a public URL, or sent anywhere merely by saving them. Sending to an original frame uses SwitchBot's cloud; Frame 2 Bluetooth-only delivery stays local after setup.

The gallery is not a playlist synchroniser: selecting/sending a gallery picture adds or reuses frame storage according to the main uploader. The separate bin reminder owns one reusable notification slot and cleans up its device copy after restoring your previous artwork.
