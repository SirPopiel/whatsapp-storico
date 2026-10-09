# WhatsApp Storico project instructions

- Keep WhatsApp message exports, databases, generated reports, device backups, and `name_overrides.local.json` local. Never commit them or send them to external services.
- After changing dashboard markup, styles, or chart behavior, regenerate `report/dashboard.html` from the latest local `report/statistiche.json` with `python3 build_dashboard.py` before finishing. If the report is absent, first run the normal local update flow when its source backup is available; do not fabricate report data.
- The normal `bash aggiorna.command` flow already regenerates the dashboard after extracting/comparing and analyzing the iPhone backup.
- Run `python3 -m unittest discover -s tests -v`, `python3 -m py_compile update.py iphone_pipeline.py build_dashboard.py`, and `bash -n aggiorna.command` after code changes.
- Keep private contact-name corrections in the ignored `name_overrides.local.json`; `name_overrides.json` is the shareable empty base.
