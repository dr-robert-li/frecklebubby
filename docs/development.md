# Development

This guide tells you how to run the app without containers and how to run the tests.

## Development

Without containers you need Python 3.14 with [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and a
llama.cpp `llama-server` for the AI functions.

```bash
uv sync --extra import                         # Python packages (with the Huckleberry import)
(cd frontend && npm ci && npm run build)       # web app, built into src/frecklebubby/static
AUTH_MODE=dev LLM_BASE_URL=http://127.0.0.1:8082/v1 uv run frecklebubby   # http://127.0.0.1:8000

llama-server -hf unsloth/gemma-4-E4B-it-GGUF:Q4_K_M --no-mmproj --jinja --reasoning-budget 0 \
  --chat-template-kwargs '{"enable_thinking":false}' -c 8192 --host 127.0.0.1 --port 8082
```

For frontend work with hot reload: `cd frontend && BACKEND=http://127.0.0.1:8000 npm run dev`.

Tests:

```bash
uv run pytest                  # backend: services, API, isolation, timers, reminders, AI with a fake model, import
uv run ruff check
cd frontend && npm run check   # type check the web app
cd e2e && npm ci && npx playwright install chromium
npx playwright test --project phone             # app journeys, AI mocked
npx playwright test --project llm               # AI journeys with the real model at LLM_BASE_URL
npx playwright test --project m4 --project m5   # reminders and push; Huckleberry import (fake account)
```

The e2e tests act as a parent on a phone screen. They start the real backend with an empty database. The `llm`,
`m4` and `m5` projects use a second backend with `LLM_BASE_URL` (default `http://127.0.0.1:8082/v1`) and the fake
Huckleberry account. Videos, traces and screenshots go to `e2e/recordings/<milestone>/` (not in git).
Open a trace with `npx playwright show-trace <file>/trace.zip`.

There is one more project for each of these areas. Run one with `--project <name>`, or run `npx playwright test`
for all projects.

| Project | Area | Needs |
|---|---|---|
| `m8` | Cry helper | The `cry` extra, `ffmpeg`, and a recording of a baby that cries (`CRY_E2E_CLIP`). Skipped without the recording |
| `m9` | Activities, nappy details, confined time | No model |
| `m11`, `m13`, `m14` | Support report, development guidance, logging from the chat | The real model |
| `m15` | Delete data, and the waiting and busy states of the assistant | The real model |
| `m17` | Invite-only server | No model |
| `m18` | Voice commands | The real model, the `voice` extra, and a recording of the words (`VOICE_E2E_WAV`). Skipped without the recording |

The pictures in `docs/screenshots/` are copies of files in `e2e/recordings/<milestone>/screens/`. They have the
size of the phone screen in the tests (1082 x 2202).

What the tests do not prove yet: a carer invite and a refused email with a real Clerk account, push notifications on a real phone (headless Chromium has no push service), and import from a real Huckleberry
account.

## Contributions

The code has the licence AGPL-3.0-or-later (see `LICENSE` and `NOTICE`). When you open a pull request, you agree to
these 2 points:

- Your contribution has the same licence.
- You give Robert Li the right to also use and license your contribution under other terms.

The second point lets the owner change the licence later and keep private extensions.
