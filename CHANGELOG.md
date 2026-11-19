# Changelog

All important changes to this project are recorded in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
