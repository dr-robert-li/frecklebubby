# Sleep model research kit

This kit makes the sleep norms and checks the next-sleep predictor of Frecklebubby. It uses the infant-sleep data
of Liu et al. (2019), "Time-Series Analysis via Low-Rank Matrix Factorization Applied to Infant-Sleep Data"
(arXiv 1904.04780). Results and decisions are in `.planning/M7_SLEEP_RESULTS.md`.

## Data and licence

The data file is `data/infant_sleep_preprocessed.mat` (18 MB), from Liu et al. (2019). It is open for
non-commercial use, with attribution to the authors. The norms file made from it is bundled with the app
(`src/frecklebubby/data/sleep_norms.json`) under the same terms. The scripts write only to the folders that you
give as arguments. Keep the work folders outside version control, for example
`~/.cache/frecklebubby-research/sleep-model/`.

The data file is MATLAB v5, variable `data`, shape (730 days of age, 144 bins of 10 minutes, 700 infants).
A value is the part of the bin that the infant was asleep (0 to 1). NaN means that the day is missing.
The bins are the local clock time of each family. The data has no time zone and no daylight-saving information.

## Install

```
cd training/sleep
uv sync
```

The kit installs the app (`../..`) as a dependency, because `replay_app_db.py` and the tests call the app code.

## Run

Set two paths first:

```
MAT=data/infant_sleep_preprocessed.mat
OUT=~/.cache/frecklebubby-research/sleep-model
```

| Step | Command | Output |
|---|---|---|
| 1. Episodes | `uv run python episodes.py $MAT $OUT/work` | `episodes.pkl`, `days.pkl`, `events.pkl`, `extract_stats.json` |
| 2. Norms | `uv run python norms.py $OUT/work $OUT/sleep_norms.json $OUT/figures` | norms file, figures |
| 3. NMF-TS | `uv run python nmf_ts.py $MAT $OUT/work $OUT/figures [ITERATIONS]` | `nmf_basis.npy`, `nmf_stats.json`, figure |
| 4. Predictor | `uv run python predict.py $OUT/work $OUT/sleep_norms.json $OUT/work` | `predict_results.json`; adds the `model` block to the norms file |
| Replay | `uv run python replay_app_db.py DB_FILE CHILD` | metrics for one child of a Frecklebubby database |
| Plan replay | `uv run python replay_plan.py $OUT/work $OUT/replay_plan.json` | rule checks, fit to the next 7 days and settings for the day and night plan, with a test split (about 10 seconds) |
| Tests | `uv run pytest` | |

Step 1 takes about 1 minute. Step 3 takes about 20 minutes on a 16-core CPU. Step 4 takes about 25 minutes.

## Rules for the episodes (step 1)

- A run of observed days is a segment. An episode never joins across a missing day.
- A partial bin has round(10 × value) minutes of sleep. The minutes go to the side of the bin next to the
  neighbour that is more asleep. With equal neighbours they go to the middle of the bin.
- A wake gap of 10 minutes or less joins the two sleeps. A sleep under 5 minutes after this step is removed.
- An episode that touches the start or the end of a segment is censored. A night with a censored episode is not used.
- Night D: the anchor is the episode with the largest overlap with D 19:00 to D+1 07:00 (60 minutes or more).
  Episodes that start between D 18:00 and D+1 08:00 and are 70 minutes of wake or less from the night join it.
  The 70 minutes is the 90th percentile of wake gaps between two episodes that are both in 23:00 to 05:00.
- A sleep-day is from the morning wake (end of night D-1) to bedtime (start of night D). Sleeps between are naps.
- A scorable event is each wake in a sleep-day that is followed by a nap or by bedtime. Night wakings are not scored.

## Use the norms file in the app

Copy `sleep_norms.json` to the data folder of the app (`DATA_DIR/sleep_norms.json`), or set `SLEEP_NORMS_PATH`.
Without the file the app uses its old wake-window table.

## Plan replay (day and night plan)

`replay_plan.py` runs the calculator of the day and night plan (`services/regime.py`, the function `calculate`) on
each infant at each 14 days of age, with the 23 days before as the logs, at 10:00 of the day. The data has sleep
only, so feeds are not replayed.

- **Rule checks** (all infants): errors, blocks that overlap, a block shorter than 5 minutes or longer than 16
  hours, a night block outside 6 to 15 hours, total sleep outside 4 to 22 hours. Also how often the plan takes a
  step, and how often it says "rough guide".
- **Fit** (test infants: the last 20 % of the split of `predict.py`): the start point of the plan (no steps)
  against the medians of the next 7 days. Two simple plans for comparison: the same as yesterday, and typical for
  the age.
- **Settings**: the days of logs that the plan reads and the days from which it uses only the infant's own values.
  Read the train column to select, and the test column to report.

Results of 2026-11-22 (app 0.7.1, 13,823 plans, 678 infants, 140 test infants):

| Measure (test infants, all ages) | Plan | Same as yesterday | Typical for the age |
|---|---|---|---|
| Bedtime, mean error | 19 min | 36 min | 45 min |
| Wake time, mean error | 22 min | 34 min | 41 min |
| Nap start, mean error | 30 min | 45 min | 52 min |
| Same number of naps | 71 % | 60 % | 64 % |
| Sleep in 24 hours, mean error | 35 min | 67 min | 54 min |

- No error and no rule fault in 13,823 plans.
- Days of logs: 7 days is worse (bedtime 20.7 min); 14 and 21 days are the same (19.1 min). The days from which
  only the own values count (3, 5 or 7) make no difference. So 14 and 5 stay.
- The plan takes a step up in 71 % of the plans at 0 to 3 months, 37 % at 3 to 6 months, 19 % at 6 to 12 months and
  6 % after that. Nearly all are the smallest step (15 minutes), because the logged sleep is inside "may be
  appropriate" but below "recommended". Parents do not log all sleep, so logged sleep is near the low edge.
- The plan says "rough guide" in 0.1 % of the plans below 6 months, 4 % at 6 to 12 months and 1 % or less after
  that. Before 0.7.1 it was 36 % at 0 to 3 months and 17 % at 3 to 6 months, nearly always because the number of
  naps is different from day to day. That is normal for a young baby, so from 0.7.1 it is a doubt only from 6
  months. With it, the steps at 0 to 3 months went from 43 % to 71 % of the plans, because a rough guide takes no
  steps.
- Limits: the norms file of the app was made from all infants of this data. Parents who log in an app are not all
  parents. The data has no feeds and stops at 24 months.
