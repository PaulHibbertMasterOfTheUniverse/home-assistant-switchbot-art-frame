# Copy into a new ChatGPT chat

Help me install and use this Home Assistant integration:
https://github.com/PaulHibbertMasterOfTheUniverse/home-assistant-switchbot-art-frame

Read the README, the latest release notes, docs/PRIVACY.md and docs/TROUBLESHOOTING.md before giving instructions. If you cannot access those files, say so and ask me to paste the relevant non-private documentation; do not invent setup steps.

First establish my frame generation, exact screen size, Home Assistant version and whether I have a working connectable Bluetooth adapter or active proxy. The validated Frame 2 profile is 13.3-inch. Frame 2 supports local Bluetooth uploads after initial account/key setup; original Frame 1 new uploads require SwitchBot cloud/Wi-Fi. Do not call Wi-Fi mode local or imply that online AI generation runs locally.

Guide me through the published install/setup flow a small number of steps at a time. The package includes the integration, a dashboard card and optional notification-switch behaviour. It does not automatically configure Alexa or Google Home account linking. I can use the optional baby-asleep example or my own image.

Keep my credentials, tokens, Bluetooth keys and account files private. Tell me where to enter them directly in my own Home Assistant rather than asking me to paste them into this chat. Do not ask for packet captures or certificate installation as a normal setup step.

When troubleshooting, distinguish a server accepting a command, a frame reporting stored/selected, and a physically correct settled screen. Ask which of these was observed. Preserve existing artwork: the dashboard's oldest-picture replacement is an explicit confirmation, and a cloud entry is backed up before removal. Do not suggest factory resetting a frame as a first response to a failed upload.

Check my installed version against the release documentation, and explain known beta limitations accurately. If something is not established for my hardware or firmware, say that. Do not claim the project works with every frame size or with any Shelly Bluetooth plug automatically.

For 0.7.0-beta.1 also read docs/GALLERY.md and docs/BIN-REMINDER.md. Guide users through saving/reusing private gallery artwork. Bin reminders are optional, currently tested only on original 31.5-inch Wi-Fi/cloud frames; they require the extra component, a user-owned collection calendar or Erewash UPRN, and an explicit enable step. Never invent collection dates or infer a cancellation from an unavailable calendar. Never ask users to post credentials, UPRNs, household photos or private HA configuration in GitHub issues.

Before requesting any address or council information, ask whether the user wants optional bin-day reminders. If not, skip all location and bin setup. Reminders default to off; explain the dashboard Enable/Disable bin reminders button after optional configuration. Disabling prevents future scheduled displays while completing any pending restore and cleanup.
