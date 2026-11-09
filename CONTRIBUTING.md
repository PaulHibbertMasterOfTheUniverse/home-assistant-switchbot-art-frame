# Contributing

Use Python 3.14.2 or newer and an isolated environment. The current public setup is validated against Home Assistant 2026.11.0.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -p 'test_*.py'
node --check custom_components/switchbot_frame_control/frontend/frame-upload-card.js
node tests/test_card_memory.cjs
node tests/test_card_preparation.cjs
python tools/check_public.py
python tools/build_release.py
```

Tests use synthetic device identities, passwords and pictures. Do not add captures, private account files, real device IDs, local machine paths, home addresses, private image URLs or personal screenshots to tests or issues. The optional licensed example photo is the only deliberately included personal image.

Prefer a targeted regression test and state exactly which generation, panel size, firmware and transport was physically tested. Do not enable an untested panel profile solely because its API model name looks similar. Do not infer physical display success from cloud command acceptance.

The public candidate is kept separate from any existing developer installation. A passing mocked API test is not a hardware compatibility claim. Share concise, redacted status/error details when reporting bugs.
