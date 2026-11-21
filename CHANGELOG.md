# Changelog

All important changes to this project are recorded in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.8.3] - 2026-11-22

### Changed

- History, List view: the button "Show older" is now "Show more", because the list is not always in the order of time.

### Fixed

- History, List view: the "Show more" button and the "Download this list as CSV" button now have space between them.

## [0.8.2] - 2026-11-22

### Added

- History, List view: "Download this list as CSV". The file has all entries of the selected types and days, in the order of the list. The format is the same as the CSV of the Reports page.
- API: `GET /children/{id}/export.csv` accepts `type`, `from`, `to`, `sort` and `dir`, as the entry list does. With no parameter it gives all entries, the oldest first, as before.

## [0.8.1] - 2026-11-22

### Changed

- History, List view: "Days" is now a range with a first day and a last day, selected in the calendar of the device. A range can have 180 days at most. Buttons select the last 7 days, the last 30 days, or all days. Before, it was a list of 30 checkboxes.
- History: Day, Week and Month show the newest first. In Day the newest entry is at the top. In Week and Month the newest day is at the top.

### Added

- Reports: you can show the charts for a week or for a month (the last 30 days).
- Reports: each chart has a dotted line at the average of a day, and the key shows the value. Days before the first logged day do not count.

## [0.8.0] - 2026-11-22

### Added

- History has two new views, Week and Month. The views are now Day, Week, Month and List.
  - Each day is one row, with the 24 hours from left to right. Sleep is a bar. Each other entry is a mark at its time, in the colour of its type.
  - Week shows the 7 days to the selected day in tall rows, with one lane for each group (sleep, feeds, nappies, other) and the totals of the day under each row.
  - Month shows the 30 days to the selected day in thin rows, with the hours of sleep at the end of each row.
  - The type checkboxes select what the views show. A row opens its day in the Day view. A sleep that goes past midnight shows in the two days.
  - Each type has its own colour, and a key above the rows shows the colours.
- History, List view: "Days" is a list of the last 30 days with checkboxes. The list then shows only the selected days together, with the number of entries and, in the order of volume or duration, the total. With no day selected, the list shows all days.

### Changed

- History, List view: the list has no day headings. Each row shows its date.

### Fixed

- History: the text of the "Types" control is now in the middle of its box.

## [0.7.2] - 2026-11-22

### Changed

- History, Day view: the day now reads from the morning to the evening. Before, the newest entry was first.
- History: the type filter is a list of checkboxes, so you can show one type or more. It has "Select all" and "Deselect all".

### Added

- History, List view: "Order by" time, duration, volume, weight, length or height, head, or temperature, each with the largest or the smallest first (for time: the newest or the oldest first). In the order of an amount, the list shows only the entries that have this amount, and each row shows its date.
- API: `GET /children/{id}/entries` accepts `type` more than one time, `sort` (`time`, `duration`, `volume`, `weight`, `height`, `head`, `temperature`), `dir` (`desc`, `asc`) and `offset`.

## [0.7.1] - 2026-11-22

### Changed

- For a baby younger than 6 months, a different number of naps from day to day no longer makes the plan a "rough guide". It is normal at this age. In the replay on the research data, a third of the plans at 0 to 3 months were a rough guide, and a rough guide takes no steps.

### Added

- `training/sleep/replay_plan.py`: a replay of the day and night plan on the research data of Liu et al., with rule checks, the fit to the next 7 days and a test split. Results are in `training/sleep/README.md`.

## [0.7.0] - 2026-11-21

### Added

- Sleep training, as an option (**Assistant > Sleep plan > Sleep training**). It is off by default. With the mode off, the sleep plan works as before.
- Three methods: graduated extinction, extinction, and bedtime fading. Each has parental presence as an option.
- Age limits, with the corrected age for a baby born early: not available below 4 months; from 4 to 6 months only graduated extinction, after a warning that the parent confirms; from 6 months graduated extinction and extinction; bedtime fading from 12 months.
- A pace on a scale from 1 (gentle) to 10 (firm). For graduated extinction the waits go from a fixed 2 minutes, through 2, 4, 6, 8, 10 minutes (the usual schedule of the trials), to 5, 10, 15 minutes. No wait is longer than 15 minutes. With parental presence, the scale sets the nights for each step: 4 to 1.
- A switch for the scale: the parent's answer after each night ("too hard", "all right", "it can go faster") moves the scale one step for the next night, or the scale stays and the parent moves it by hand.
- The steps for tonight, a report for each night (minutes to fall asleep, wakes, minutes of crying), and a review: the goal holds for 3 nights, no gain after 7 nights, or 14 nights are over.
- A prompt to pause when a fever or a medicine is logged in the last 24 hours. Feeds that the child still needs at night stay in the plan.
- While sleep training runs, the day and night plan takes no step at bedtime. With bedtime fading, the night block of the plan shows the bedtime of the training.
- API `GET`, `PUT` and `DELETE /children/{id}/sleep/training`, and `POST /children/{id}/sleep/training/nights`.

## [0.6.5] - 2026-11-21

### Fixed

- The "Write new sleep plan" button touched the source chips above it. It now has space above it. The same fault was in **Settings > Children** ("Add a child"), and it is fixed there too. A test now checks the space above the wide buttons on the main pages.

## [0.6.4] - 2026-11-21

### Fixed

- The plan for a young baby showed too few sleeps in the day, and some feeds in a row with no sleep between them. The sleeps of the day are often at different hours from day to day, so the night took all the sleep blocks. The plan now counts the usual number of sleeps for the day and for the night separately.

### Changed

- The button under the plan is "Write a sleep plan" again (then "Write new sleep plan"), and the part that the assistant writes is named "Sleep plan in words".

## [0.6.3] - 2026-11-21

### Fixed

- The totals under "Today" on Home are now in two rows. Sleep and Breastfed are in the first row, so their times stay inside the cards. Wee, Poo and Bottle are in the second row.

## [0.6.2] - 2026-11-21

### Changed

- The steps of the day and night plan now use the three bands of the National Sleep Foundation for each age: recommended, "may be appropriate", and not recommended.
- A little too little sleep (below the recommended range, but inside "may be appropriate"): the smallest step, 15 minutes. Much too little sleep: a quarter of the gap, from 15 to 60 minutes, and the page says to speak to a doctor or nurse when the logs are complete.
- More sleep than recommended is never cut. No source says to cut the sleep of a healthy child. Inside "may be appropriate" the page has one note. Above it, the page says to check the logs for a sleep timer that was not stopped, and then to speak to a doctor or nurse, with the warning signs.
- From 2 years: when a nap is longer than 2 hours or ends after 15:00, and the night sleep starts late or is short, the plan ends the nap 15 minutes earlier.
- The page shows the child's number of sleeps in the day next to the typical number for the age. The plan takes no step toward the typical number, because no source recommends a number of naps.
- The recommended range in the plan is now the one of the National Sleep Foundation for all ages (for example 12 to 15 hours at 4 to 11 months).

## [0.6.1] - 2026-11-21

### Changed

- The day and night plan is now one timeline of sleep blocks and feeds, from the morning. Each nap and the night sleep is a block with a start and an end. The feeds of the day and of the night are rows in the same timeline. The "wake up", "bedtime" and "night wake" rows are gone.
- Small steps toward best practice. The start point is the child's own logs of the last 14 days. When the logs show less sleep in 24 hours than the recommended range for the age, the plan adds a small amount of sleep: a quarter of the gap, from 15 to 60 minutes. It moves bedtime earlier by 20 minutes at most, or makes naps a little longer. The page says what changed and why. The next plan starts from the new logs, so the plan does not run ahead of the family.
- A young baby with fewer than 8 feeds in 24 hours in the logs gets 1 more feed in the plan, in the longest time between two feeds. In the first 4 weeks the plan also adds a feed when more than about 4 hours pass at night.

- A fit check. When the logs do not fit a pattern that the calculator knows (for example no night sleep that the app can find, or a different number of naps each day), the page says so. The plan is then a rough guide and takes no steps.
- Feeds that start within 45 minutes of each other count as one feed (for example the left and the right side).

### Fixed

- The plan for a baby younger than 12 weeks. A young baby has no fixed day and night, so the plan showed a bedtime after midnight and one nap. The plan now takes the baby's usual number of sleeps in a day and puts them at the times of the day at which the baby sleeps most often. When the logs show too little sleep, the plan adds one new sleep block in the longest time with no sleep.

## [0.6.0] - 2026-11-21

### Added

- Day and night plan (**Assistant > Sleep plan**): one typical 24 hours for the child, with the wake time, the naps, bedtime, and the usual night feeds and night wakes. The app calculates it; the AI model does not make the times.
- The plan uses the child's own logs of the last 14 days first. Each time is the middle value of those days, so one unusual day does not change the plan. From 5 complete days, only the child's own times are used. With fewer days, the plan mixes them with typical times for the age and says so.
- The page shows the child's own numbers (sleep in 24 hours, sleep at night, longest sleep, wakes and feeds at night) next to the range that is common for the age. The range is information, not a target.
- Rules that change with the age, in 7 age bands from birth to 5 years, each with its source.
- Numbers for the age from published studies, with links: Paavonen 2020, Galland 2012, Blair 2012, Iglowstein 2003, Staton 2020, Brown and Harries 2015. The plan now also covers children from 2 to 5 years.
- API `GET /children/{id}/sleep/regime` and the MCP tool `get_day_and_night_plan`.

### Changed

- "Make a sleep plan" is now "Write advice for this plan". The AI model gets the calculated plan and writes a summary and tips with sources. It cannot change the times.

## [0.5.3] - 2026-11-21

### Added

- Voice commands show progress. After you speak, the voice card shows a moving bar and a line of text while the server changes the speech into words, and while the assistant works. Your words show as soon as the server has them.

## [0.5.2] - 2026-11-21

### Fixed

- A sleep plan now shows a full day. It starts with the wake at the "Morning starts" time of the child. Before, the plan started after the time now.

## [0.5.1] - 2026-11-21

### Added

- Home: you can change the size and the place of each card. Hold a card to start. Then select Small, Large or
  Wide, and drag the card to a new place (or use "Move earlier" and "Move later"). A tap outside the cards ends
  the mode. "Reset" gives the first layout back. The layout is kept on the device.
- Home: a large card shows when the last entry was. A wide card shows a short description and when the last
  entry was. All cards can have each size.

### Changed

- The README is shorter. The guides for sign-in, HTTPS, the API and MCP, the AI parts, operations and development
  are in `docs/`.
- New screenshots, with the voice commands and the card layout.

## [0.5.0] - 2026-11-21

### Added

- Voice commands. A talk button (microphone) and a hands-free button (wave) are next to "Tell me what happened"
  on Home and next to the question box in the Assistant. The words go to the assistant, which logs them or
  answers them.
- Hands free: say "Hey Bubby" or "OK Bubby" and then your words. The app makes a short sound when it hears the
  keyword, and keeps the screen on while hands free is on.
- Settings > Voice: an optional large hold-to-talk button on the left or right side of the screen at a height you
  select, and an option to read the answer aloud (off, hands free only, all voice commands).
- Speech to text runs on your own server (Whisper `small.en` on the CPU, the new `voice` extra). The audio is not
  stored. New settings: `VOICE`, `WHISPER_MODEL`, `WHISPER_LANGUAGE`, `LIMIT_VOICE`.
- API: `POST /voice/transcribe`; `POST /children/{id}/assistant/chat` takes `voice: true`; `/config` has `voice`;
  a logged item can have `unsure`.

### Changed

- A voice command saves its entries immediately, also when the app is not sure. Such an entry shows
  "Not sure: …" and can be undone. Typed words work as before: the app asks before it saves a guess.
- The day theme has a beige cream background in place of the bright white tone.

### Fixed

- Import from Huckleberry: the radio buttons were very large and not in line with their text.

## [0.4.3] - 2026-11-21

### Changed

- Assistant: when the sources do not cover a question, the answer lists up to three trusted pages on the topic
  as links. The list comes from fixed rules and the source list, not from the model.
- Assistant: the search and the web lookup find better pages. A word in the title or the topics of a page counts
  more, common words ("baby", "week", "normal") count nothing, and "settle" and "nap" find the sleep pages.

### Fixed

- The same passage could show two times in the sources of one answer, and two questions at the same moment could
  store one web page two times.
- The test of the nappy rash card failed each day from 02:00 to 06:00 Brisbane time.

## [0.4.2] - 2026-11-21

### Added

- Settings > Delete data: the owner can delete one child and all the data of that child. Select the child and
  type the name to confirm. API: `DELETE /children/{id}/permanent`.
- Settings > AI model shows the approved websites for web lookup. The README says how to change the list.
- Huckleberry import: select where the data goes, a new child (as before) or a child you have now. The page says
  where the data is when the import is done. API: the optional field `child_id` of `POST /import/huckleberry`.

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
