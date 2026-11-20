# Development items: notice

File: `development.json`. Research notes: `.planning/M13_RESEARCH.md` (not versioned).

Each item is a fact about child development that the CDC checklist (`milestones.json`) does not have. Every item names
a bundled library file (`library`, in `data/library/`, add `.md`) and an exact phrase of that file (`phrase`) that
supports it. `tests/test_library_m13.py` checks the phrases.

## Fields

- `key`: stable and unique.
- `domain`: `physiological`, `behavioural` or `activity`.
- `text`: what a parent may see, in our short words, with the meaning of the source. Never a diagnosis.
- `from_days`, `typical_days`, `to_days`: age in days from birth. `null` where the source gives no such value.
  - A window (`from_days` and `to_days`) is the range the source gives. WHO motor items use the 1st and 99th
    percentiles; `typical_days` is the WHO 50th percentile.
  - "by X" in the source is `to_days`; "around X" or "at X" is `typical_days`; "from X" is `from_days`.
  - Conversion: WHO items use the days that WHO publishes. Other items: months x 30.4375 (the WHO convention),
    years x 365.25, weeks x 7, rounded to whole days. "1 to 2 years" ends at 3 years minus 1 day (and so on).
- `tip`, `tip_library` (optional): an exact sentence from a library file that gives a way to help.
- `source`: title, publisher and URL of the original page or paper.

## Corrected age for premature babies

Ages are for babies born at term. Two sources give a rule for babies born early: use the corrected age (age from the
due date) until 2 years. Library file `corrected-age-premature`, phrase: "until they are 2 years old." (NHS) and
"to track development until 2 years of age" (AAP). Neither source gives a rule after 2 years.

## Licences

- CDC text was changed in one way: the app changed gendered pronouns (he, she, him, her, his) to they, them and their. It made no other change.
- CDC text: public domain (US government work). Material developed by CDC; reference does not imply endorsement by
  CDC, HHS or the U.S. Government.
- nhs.uk text: Open Government Licence v3.0.
- NHS Best Start in Life pages are Crown copyright with all rights reserved, not OGL: the library holds only our own
  short summary.
- WHO, AAP (HealthyChildren.org), NICE and journal papers: our own short summaries of published facts, with links.
  WHO material is CC BY-NC-SA 3.0 IGO; WHO does not endorse this text.

Schedules of health checks and vaccines are from England (NHS). Other countries differ. Items that name a check say so.
