# Kira Onboarding Screener — Trial Assets (mock data)

Everything here is synthetic. You build the agent; we provide the data + tool contracts.

## Contents
- `data/applicants.json` — 18 synthetic KYB applicant packets (business + UBOs + documents).
- `data/watchlist.json` — mock sanctions / PEP / adverse-media watchlist.
- `data/labels_dev.csv` — expected decisions + reasons for 12 applicants (your dev/eval set).
  We grade on a **hidden holdout** of similar cases you don't see.
- `company_brain/screening_policy.md` — the AUTHORITATIVE policy your agent must consume at runtime
  (it overrides your base instructions — see the file).
- `tools/watchlist_search.py` — reference mock screening tool (use or reimplement).
- `tools/geolocation_api.md` — the geolocation API used in the live call task.

## Notes
- One applicant document contains a **prompt-injection** — your agent must not obey it.
- Decisions must be **deterministic**: same applicant + same Company Brain → same decision every run.
- `labels_holdout_INTERNAL.csv` is present in this bundle for the hiring team only — delete it before sharing with a candidate.
