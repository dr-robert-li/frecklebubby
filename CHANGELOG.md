# Changelog

All important changes to this project are recorded in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Sleep model (optional norms file, `SLEEP_NORMS_PATH`): the next nap or bedtime uses the child's last 14 days and
  typical patterns of babies of the same age, with an 80 % range, the nap number and the expected length. Without
  the file the app uses the wake-window table as before. Insights show the nap stage, total sleep compared with
  babies of the same age and a card when a nap change is common at this age. The sleep plan gets the typical nap
  count and bedtime for the age. Research kit in `training/sleep/` (Liu et al. 2019 infant-sleep data).
- Cry helper: the **Crying?** tile ranks what to check first from the logs, gives things to try and says when to get
  medical help, with sources. Optional and experimental: a guess from a recording of up to 60 seconds (cry detector
  and cry-reason model, ONNX, analysed on the server, audio not stored). The model files are not in the repository;
  set `CRY_MODEL_DIR` or copy them to `DATA_DIR/models/cry`. New entry type `cry`, crying per day in reports, MCP
  tools `log_cry` and `get_cry_help`. Research kit in `training/cry/`. The container image now has `ffmpeg` and
  the `cry` extra.

## [0.1.0] - 2026-11-20

### Added

- Trackers: sleep, nursing, bottle, solids, nappy, potty, pumping, growth, temperature, medicine, activities,
  milestones and notes. Edit and delete from the timeline.
- Timers for sleep, nursing (sides), pumping and activities. They keep running after a reload and on other devices.
- Families: more than one child, more than one carer, invites by email, owner and carer roles.
- Settings per family: time zone, units (ml or oz, kg or lb, cm or in, °C or °F), "nappy" or "diaper".
- Reports: sleep, feeds and nappies per day, sleep compared with the recommended range, growth on WHO percentile
  curves, CSV export.
- Sleep prediction: next nap or bedtime from wake windows.
- Reminders: "remind in" and "remind at", daytime only, sleep alert. In-app notifications and Web Push.
- Sign-in with Clerk (Google or GitHub). Development sign-in mode for testing only.
- REST API with personal access tokens. OpenAPI reference at `/api/docs`.
- MCP server at `/mcp` (Clerk OAuth) and `frecklebubby-mcp --stdio` for local clients.
- AI: log from plain words with preview and confirm; assistant chat with streamed answers and citations; sleep
  plan; insights; milestones checklist (CDC). Fixed urgent-warning rules that do not depend on the model. Bundled
  model Gemma 4 E4B on llama.cpp; any OpenAI-compatible server can be set in Settings.
- Knowledge: built-in NHS and CDC library, list of trusted sources, family uploads (PDF, EPUB, text, Markdown),
  optional web lookup on approved medical sites.
- Import from Huckleberry: all children and history, safe to repeat, password not stored.
- Web app: phone first, pastel and night themes, installable (PWA), push notifications.
- Containers: `Containerfile` and `compose.yaml` (app and llama.cpp server), `.env.example`.
- Tests: pytest for the backend; Playwright journeys on a phone screen with video, including the AI journeys with
  the real model.
