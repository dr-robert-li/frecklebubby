<div align="center">

<img src="frontend/static/icon.svg" alt="Frecklebubby icon" width="112" height="112">

# Frecklebubby

**A baby tracker that you host yourself.**

Log the day, see the patterns, and ask an assistant that shows its sources.
Your data stays on your server.

[![CI](https://github.com/dr-robert-li/frecklebubby/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-robert-li/frecklebubby/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.8.5-e88fa6)](CHANGELOG.md)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-7fb8a4)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-6c9bd2)](pyproject.toml)

[Quick start](#quick-start) · [Connect Claude](docs/api-and-mcp.md#connect-claude-mcp) · [Screenshots](#what-it-does) · [Changelog](CHANGELOG.md)

</div>

---

## What it does

- Tracks sleep, breastfeeding, bottles, solids, nappies, potty, pumping, growth, temperature, medicine, activities
  (bath, tummy time, indoor and outdoor play, story time, screen time, skin to skin, brushing teeth), time in a
  car seat or other seat, crying, milestones and notes.
- Lets you set up the Home screen: hold a card, then change its size (small, large with the time of the last
  entry, wide with a description) and drag it to a new place.
- Shows the totals of today on the Home screen (sleep, breastfeeding, wee, poo, bottle) and the entries of the day.
- Supports more than one child and more than one carer. Carers join by invite.
- Can serve more than one family from one server, invite only. Each family sees only its own data. An owner can
  delete the family and all its data.
- Has live timers for sleep, breastfeeding, pumping, activities and confined time. Activity timers can
  run side by side, one for each kind (for example indoor play and tummy time). A timer
  keeps running when you close the app.
- Tells you when a child has been in a car seat, bouncer, swing, pram, carrier or high chair for a long time: a
  note at 1 hour (children under 5 years) and a break warning at 2 hours (children under 12 months), with sources.
- Records nappy details: rash, time with the nappy off, poo colour and texture, pee colour, look and smell.
- Shows the history by day, week or month, or as a list. Week and month show each day as one row of 24 hours,
  with sleep as bars and feeds and nappies as marks, so you see the pattern. You select the types to show, and
  you can put the list in the order of time or of a logged amount (duration, volume, weight, length, temperature).
  In the list you can also select a range of days (180 days at most), to see them together with a total, and download the list as a CSV file.
- Shows reports: sleep, feeds and nappies per day for a week or a month, with the average and the common range,
  and growth on WHO percentile curves. Exports CSV.
- Sends reminders in the app and as push notifications.
- Has a REST API and an MCP server, so scripts and AI assistants such as Claude can read and write the data.
- Has an AI assistant that runs on an open model on your own server. It logs from plain words
  ("120 ml formula 20 minutes ago") on the Home screen and in the chat, answers questions with citations to
  medical sources, writes a sleep plan in words, and shows insights.
- Takes voice commands, so you can log and ask with no hand or one hand free: a talk button, hands free with the
  keyword "Hey Bubby" or "OK Bubby", an optional large hold-to-talk button on the side of the screen, and an option
  to read the answer aloud. Your own server changes the speech into text. The app shows the progress while you wait.
- Calculates a day and night plan for each child: a timeline of sleep blocks and feeds. It starts from your
  child's own logs of the last 14 days. When the logs are outside a recommended range, it moves toward the range
  in small steps and says what it changed.
- Has sleep training as an option, off by default: graduated extinction, extinction or bedtime fading, each
  with parental presence if you want, on a scale from gentle to firm, with age limits and a review of each night.
- Gives development guidance from birth to 5 years: what most children do by each age (CDC), movement, behaviour
  and body changes to expect around now, cited tips on how to help, and a notification at each new age band.
  For a baby born early, give the due date and the app uses the corrected age until 2 years.
- Makes a support report: the last 7 days by area, compared with cited references, with suggestions on where you
  can support your child.
- Copies your data out of the Huckleberry app, once or as often as you like.

<div align="center">

**Log the day**<br>
<sub>Home with timers · Activities, with timers side by side · Log by plain words · The assistant logs for you</sub>

<p>
  <a href="docs/screenshots/home.png"><img src="docs/screenshots/home.png" alt="Home with timers" title="Home with timers" width="23%"></a>
  <a href="docs/screenshots/activity-timers.png"><img src="docs/screenshots/activity-timers.png" alt="Activities, with timers side by side" title="Activities, with timers side by side" width="23%"></a>
  <a href="docs/screenshots/plain-words.png"><img src="docs/screenshots/plain-words.png" alt="Log by plain words" title="Log by plain words" width="23%"></a>
  <a href="docs/screenshots/assistant-logged.png"><img src="docs/screenshots/assistant-logged.png" alt="The assistant logs for you" title="The assistant logs for you" width="23%"></a>
</p>

**Ask and plan**<br>
<sub>Assistant with sources · Insights · Development guidance · Sleep plan in words</sub>

<p>
  <a href="docs/screenshots/assistant.png"><img src="docs/screenshots/assistant.png" alt="Assistant with sources" title="Assistant with sources" width="23%"></a>
  <a href="docs/screenshots/insights.png"><img src="docs/screenshots/insights.png" alt="Insights" title="Insights" width="23%"></a>
  <a href="docs/screenshots/development.png"><img src="docs/screenshots/development.png" alt="Development guidance" title="Development guidance" width="23%"></a>
  <a href="docs/screenshots/sleep-plan.png"><img src="docs/screenshots/sleep-plan.png" alt="Sleep plan in words" title="Sleep plan in words" width="23%"></a>
</p>

**See the patterns**<br>
<sub>Reports · Support report · Cry helper · Confined-time warning</sub>

<p>
  <a href="docs/screenshots/reports.png"><img src="docs/screenshots/reports.png" alt="Reports" title="Reports" width="23%"></a>
  <a href="docs/screenshots/support-report.png"><img src="docs/screenshots/support-report.png" alt="Support report" title="Support report" width="23%"></a>
  <a href="docs/screenshots/cry-helper.png"><img src="docs/screenshots/cry-helper.png" alt="Cry helper" title="Cry helper" width="23%"></a>
  <a href="docs/screenshots/confined.png"><img src="docs/screenshots/confined.png" alt="Confined-time warning" title="Confined-time warning" width="23%"></a>
</p>

**Run a server for more than one family**<br>
<sub>Server access for the operator · Refused sign-in · Delete data · Waiting for the assistant</sub>

<p>
  <a href="docs/screenshots/server-access.png"><img src="docs/screenshots/server-access.png" alt="Server access for the operator" title="Server access for the operator" width="23%"></a>
  <a href="docs/screenshots/no-access.png"><img src="docs/screenshots/no-access.png" alt="Refused sign-in" title="Refused sign-in" width="23%"></a>
  <a href="docs/screenshots/delete-data.png"><img src="docs/screenshots/delete-data.png" alt="Delete data" title="Delete data" width="23%"></a>
  <a href="docs/screenshots/assistant-waiting.png"><img src="docs/screenshots/assistant-waiting.png" alt="Waiting for the assistant" title="Waiting for the assistant" width="23%"></a>
</p>

**Hands free and your own layout**<br>
<sub>Voice command · Voice settings · Change the Home cards · Day and night plan</sub>

<p>
  <a href="docs/screenshots/voice.png"><img src="docs/screenshots/voice.png" alt="Voice command" title="Voice command" width="23%"></a>
  <a href="docs/screenshots/voice-settings.png"><img src="docs/screenshots/voice-settings.png" alt="Voice settings" title="Voice settings" width="23%"></a>
  <a href="docs/screenshots/home-cards.png"><img src="docs/screenshots/home-cards.png" alt="Change the Home cards" title="Change the Home cards" width="23%"></a>
  <a href="docs/screenshots/day-night-plan.png"><img src="docs/screenshots/day-night-plan.png" alt="Day and night plan" title="Day and night plan" width="23%"></a>
</p>

**History and sleep training**<br>
<sub>History by week · History by month · History list, in order of amount · Sleep training</sub>

<p>
  <a href="docs/screenshots/history-week.png"><img src="docs/screenshots/history-week.png" alt="History by week" title="History by week" width="23%"></a>
  <a href="docs/screenshots/history-month.png"><img src="docs/screenshots/history-month.png" alt="History by month" title="History by month" width="23%"></a>
  <a href="docs/screenshots/history-list.png"><img src="docs/screenshots/history-list.png" alt="History list, in order of amount" title="History list, in order of amount" width="23%"></a>
  <a href="docs/screenshots/sleep-training.png"><img src="docs/screenshots/sleep-training.png" alt="Sleep training" title="Sleep training" width="23%"></a>
</p>

<sub>Select a picture to see it in full size.</sub>

</div>

## Not medical advice

Frecklebubby gives general information only. It is not a medical device. If you are worried about your child, speak
to a doctor or nurse. In an emergency, call your local emergency number.

## Quick start

You need Docker with Compose, or Podman with `podman compose`. You need about 6 GB of disk for the model and
8 GB of memory.

1. Get the code:

   ```bash
   git clone https://github.com/dr-robert-li/frecklebubby
   cd frecklebubby
   ```

2. Copy the settings file and fill it in. Read the comments in the file.

   ```bash
   cp .env.example .env
   ```

   For normal use you need the Clerk values (see [Clerk sign-in](docs/sign-in.md#clerk-sign-in)) and `BASE_URL`.

3. Start:

   ```bash
   docker compose up -d        # or: podman compose up -d
   ```

   This builds the app and starts two containers: `app` (Frecklebubby) and `llama` (the AI model server).
   On the first start the model server downloads the model (about 5 GB). This can take a long time.
   The app works while the download runs. Only the assistant says "The assistant is not available now".

4. Open `http://<your server>:8000` (or your `BASE_URL`). Sign in, make your family and add your child.

To see the logs: `docker compose logs -f app` or `docker compose logs -f llama`.
To stop: `docker compose down`. Your data stays in the volume `data`.

### Try it on your own computer without Clerk

Put `AUTH_MODE=dev` in `.env`. Then there is no sign-in. **Anyone who can reach the server can act as any user.**
Use this only on your own computer, never on a server that other people can reach.

## Guides

The long sections are in the `docs/` folder:

- [Sign-in](docs/sign-in.md): how to set up Clerk sign-in, and how to run an invite-only server for more than one family.
- [HTTPS and phone install](docs/https.md): how to get an HTTPS address (Tailscale Funnel, Cloudflare Tunnel or a reverse proxy), and how to install the app on a phone.
- [API and MCP](docs/api-and-mcp.md): how to connect Claude to the MCP server, and how to use the REST API with a token.
- [AI functions](docs/ai.md): the AI model and the GPU setting, the day and night plan, sleep training, the sleep model, voice commands, the cry helper, and the knowledge library with its licences.
- [Operations](docs/operations.md): how to move your data from Huckleberry, and how to back up and restore the database.
- [Development](docs/development.md): how to run the app without containers, and how to run the tests.

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| The app container stops with "Refusing to start: AUTH_MODE=clerk needs ..." | A value is missing in `.env`. The message names it. Fill it in and run `docker compose up -d` |
| "The assistant is not available now" | The model server is still downloading or starting. See `docker compose logs -f llama`. Or check the URL in **Settings > AI model** and select **Test connection** |
| Sign-in works but the app says you are not signed in | The Clerk session token has no `email` claim. Do step 3 of [Clerk sign-in](docs/sign-in.md#clerk-sign-in) |
| Claude sign-in fails with "redirect_uri ... does not match" | The Clerk OAuth application must list `<BASE_URL>/auth/callback` exactly |
| "Turn on notifications" fails, or there is no push | Push needs HTTPS. On iPhone, add the app to the Home Screen first. Check that the browser allows notifications |
| The assistant answers stop part-way through a proxy | Turn off response buffering in the proxy for `/api/` |
| A sleep plan takes long | Normal on a CPU: about 1 minute or more |
| Import says "Huckleberry sign-in failed" | Check the email and password in the Huckleberry app |
| Import says it is not available on this server | The `import` extra is not installed. The container has it. Without containers: `uv sync --extra import` |

## Licence

MIT for the code. See [LICENSE](LICENSE). Data in `src/frecklebubby/data/` keeps its own licence (see
[Knowledge library and licences](docs/ai.md#knowledge-library-and-licences)). The sleep norms file, the sleep data in
`training/sleep/data/` and the cry models are for non-commercial use, with attribution (see [Sleep model](docs/ai.md#sleep-model)
and [Cry helper](docs/ai.md#cry-helper)).

This project is not affiliated with Huckleberry Labs Inc.
