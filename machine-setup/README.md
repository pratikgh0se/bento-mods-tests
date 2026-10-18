# machine-setup contract tests

Code-blind tests written from `specs/machine-setup-spec.md` (ACs 1-83, 17a; AC 16 withdrawn).
Public tree: env `MACHINE_SETUP_REPO` (default `~/CodeBase/machine-setup`).
Run: `python3 -m unittest discover -s machine-setup`.

| File | ACs |
|---|---|
| test_bootstrap.py | 1-11 |
| test_merge.py | 41-48 (merge_settings.py + merged install) |
| test_overlay.py | 36-40, 49-55 |
| test_export.py | 12-15, 17a, 56-65 |
| test_autosync.py | 29-34, 66-69 |
| test_scrub.py | 18-21 |
| test_secretscan.py | 22-27 |
| test_leakscan.py | 28, 70-83 (incl. CI workflow, public-tree self-check) |
| test_publish_gate.py | 87-90 (public push gate) |
