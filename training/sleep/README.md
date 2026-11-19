# Sleep model research kit

This kit makes the sleep norms and checks the next-sleep predictor of Frecklebubby. It uses the infant-sleep data
of Liu et al. (2019), "Time-Series Analysis via Low-Rank Matrix Factorization Applied to Infant-Sleep Data"
(arXiv 1904.04780). Results and decisions are in `.planning/M7_SLEEP_RESULTS.md`.

## Data and licence

The data is not in this repository. The project page of the authors gives no licence. Do not copy the data file
or any row for one infant into the repository. The scripts write only to the folders that you give as arguments.
Keep these folders outside version control, for example `~/.cache/frecklebubby-research/sleep-model/`.

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
MAT=~/.cache/frecklebubby-research/liu2019/infant_sleep_preprocessed.mat
OUT=~/.cache/frecklebubby-research/sleep-model
```

| Step | Command | Output |
|---|---|---|
| 1. Episodes | `uv run python episodes.py $MAT $OUT/work` | `episodes.pkl`, `days.pkl`, `events.pkl`, `extract_stats.json` |
| 2. Norms | `uv run python norms.py $OUT/work $OUT/sleep_norms.json $OUT/figures` | norms file, figures |
| 3. NMF-TS | `uv run python nmf_ts.py $MAT $OUT/work $OUT/figures [ITERATIONS]` | `nmf_basis.npy`, `nmf_stats.json`, figure |
| 4. Predictor | `uv run python predict.py $OUT/work $OUT/sleep_norms.json $OUT/work` | `predict_results.json`; adds the `model` block to the norms file |
| Replay | `uv run python replay_app_db.py DB_FILE CHILD` | metrics for one child of a Frecklebubby database |
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
