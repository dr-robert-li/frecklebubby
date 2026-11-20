# Changelog

All important changes to this project are recorded in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.1] - 2026-11-21

### Changed

- Home: the "Today" totals always show the bottle volume, also when it is zero.
- Settings: a "Sign out" button is on the main Settings page. Before, it was only in Appearance.
- Nappies: the app says "Wee" and "Poo" where it said "Wet" and "Dirty" (form, timeline, totals, reports, plain
  words). Text from health sources keeps "wet nappies". The API values `pee`, `poo` and `both` do not change.

### Fixed

- `compose.yaml` did not pass `OPERATOR_EMAILS`, `BEHIND_CLOUDFLARE`, the `LIMIT_` settings and the `LLM_QUEUE_`
  settings to the app container. With 0.4.0 and compose, these settings in `.env` had no effect: the server was
  not invite only.
- The tests no longer read any setting from a local `.env` file.

## [0.4.0] - 2026-11-20

An invite-only server for more than one family, with protection for a public address.

### Added

- Invite only server: `OPERATOR_EMAILS` names the operators. **Settings > Server access** lets an operator invite
  an email, see invites and families, and remove an invite that is not used. An operator cannot read, change,
  block or delete the data of another family.
- Delete data: an owner can delete the family and all its data; a user can delete the account. An owner can make
  another member the owner.
- Rate limits for AI requests, uploads and wrong tokens (429 with `Retry-After`), and a queue so that the model
  takes one request at a time. New settings: `LIMIT_AI`, `LIMIT_UPLOADS`, `LIMIT_BAD_TOKEN`, `LLM_QUEUE_MAX`,
  `LLM_QUEUE_WAIT`, `BEHIND_CLOUDFLARE`.
- The chat shows "Waiting for the assistant…" while it waits, and its stream sends a heartbeat.
- An isolation test that covers every API route.

### Changed

- API: `POST /children/{id}/sleep/plan` and `POST /children/{id}/support-report` now start a job and answer 202.
  Read the state with `GET …/sleep/plan/job` or `GET …/support-report/job`, then read the result as before.
- Deleted rows are overwritten in the database file (`secure_delete`).
- The logged block in the chat shows activity kinds in plain words ("tummy time").

## [0.3.1] - 2026-11-20

The first public deployment: arm64 with an NVIDIA GPU, Docker, Cloudflare Tunnel and a real Clerk instance.
There is no release 0.3.0.

### Added

- A header with the Frecklebubby logo and name on each page.
- A button at the top right changes between day and night colours.
- Plain words read nappy amounts: "big pee", "medium poo".
- The pump timer tab says how to add the amount after the timer stops.
- Cloudflare Tunnel: an optional `cloudflared` service in `compose.yaml` (profile `tunnel`, token from `.env`).
- `compose.gpu.yaml`: run the model server on an NVIDIA GPU through CDI.

### Changed

- Home: Activity is a wide card under the four large tiles and names the activities. The nine small tiles make a
  3 x 3 grid. Confined is now before Milestone and Note. Each small tile has its own colour: Growth and Confined
  have two new colours.

- Home: the "Today" totals show the breastfeeding time ("Breastfed") in place of the number of feeds.
- The app says "Breastfeeding" where it said "Nursing".

### Fixed

- The hole of the settings gear icon is in the centre.
- The sign-in page is centred.
- Clerk sign-in showed no form. `@clerk/clerk-js` 6 gets its form from `@clerk/ui`, and the app did not load it.

- Plain words: one nappy with pee and poo gave up to 12 items. The prompt now says one nappy change is one
  event. The server joins a nappy that the model split in two. The server marks a repeated item "not sure" and does not save it twice. It drops pee details that are
  not in the parent's words.
- The support report shows the time it was made. A new report with the same content looked like nothing happened.
- The tests no longer read a local `.env` file.

### Tested

- The app image, the llama.cpp CUDA image and cloudflared run on arm64 with Docker.
- Sign-in with a real Clerk development instance, the Claude connector and the sleep plan work through the
  tunnel.

## [0.2.2] - 2026-11-20

### Changed

- One Activity type for bath, tummy time, indoor play, outdoor play, story time, screen time, skin to skin and
  brushing teeth. Activity timers run side by side, one for each kind, and each saves its own entry.
- Reports count play, tummy time and baths from activities. Time where two play timers overlap is counted once.
- Plain words and the assistant chat log baths, tummy time and play as activities. "Stop tummy time" stops that
  timer.
- The README has a new header with badges.

### Removed

- The separate Play and Bath entry types, their tiles, and the MCP tools `play_timer`, `log_play` and `log_bath`.
  Use `activity_timer` and `log_activity` with a kind.
- The "switch" action of the activity timer. Start a second timer instead.

### Migration

- At the first start, old Play and Bath entries become activities. A Play entry with a tummy part becomes two
  entries; the tummy-time entry starts at the play start (the real start is not known). Make a backup before
  the update.

### Added

- CI workflow on GitHub: web app type check and build, backend lint and tests.

## [0.2.1] - 2026-11-20

### Added

- Baths: a Bath tile to log a bath with a time and notes. Reports show the number of baths. Claude can use the new
  `log_bath` tool, and plain words such as "gave her a bath at 6" are logged as a bath. A Huckleberry bath is
  imported as a bath.

### Changed

- CDC milestone and tip text now uses they, them and their for the child. No other words were changed. The notices
  and the library files state this.

## [0.2.0] - 2026-11-20

### Added

- Play: a Play tile with a timer and a tummy-time part. Reports show play and tummy minutes per day with the WHO
  30-minute line for babies under 12 months.
- Confined time: a timer for car seat, bouncer, swing, pram, carrier and high chair. A note at 1 hour for children
  under 5 years (WHO) and a break warning at 2 hours for children under 12 months (AAP advice for car seats), in
  the app and as push notifications.
- Nappy details: rash severity, time with the nappy off, pee colour, look and smell. Rash advice card. New warning
  rules for dark pee in a newborn and for pink or red pee.
- Support report on the Reports page: sleep, feeds, nappies, play and tummy time, confined time, crying, growth and
  milestones for the last 7 days, with cited references and suggestions. Works without the model (standard tips).
- Development guidance: 33 new library files (CDC tips and activities for each age, WHO motor milestones, NHS
  pages) and 69 development items. "Around now" cards, tips on milestone cards, a notification at each new age
  band (switch in Settings > Reminders), and corrected age for babies born early (optional due date).
- The assistant chat logs what you tell it in plain words and shows a "Logged" block with Undo and Edit. When it is
  not sure, it asks before it saves.
- MCP: `log_play`, `play_timer`, `log_confined`, `confined_timer`, `get_support_report`, `log_in_plain_words`, and
  the new nappy fields. Clearer tool descriptions.
- Knowledge: WHO activity guidelines for children under 5, car seat time, NHS nappy rash, jaundice and bleeding
  pages.

### Changed

- The sleep norms file and the cry models are now bundled, so the sleep model and the cry sound guess work with no
  setup. The sleep data of Liu et al. (2019) is in `training/sleep/data/`. These files are for non-commercial use,
  with attribution.

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
