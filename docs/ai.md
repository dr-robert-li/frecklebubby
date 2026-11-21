# AI functions

This guide describes the AI model, the sleep model, voice commands, the cry helper and the knowledge library.

## The AI model

The `llama` container runs [llama.cpp](https://github.com/ggml-org/llama.cpp) with one fixed model:
**Gemma 4 E4B** (`unsloth/gemma-4-E4B-it-GGUF`, Q4_K_M, about 5 GB), licence Apache-2.0. It runs on the CPU. No GPU
is necessary.

Speed measured on a 16-thread CPU with no GPU (about 29 tokens, or word parts, per second):

| Task | Time |
|---|---|
| Log from plain words | 2 to 5 s |
| Assistant answer | 4 to 10 s |
| Sleep plan | about 1 minute |

A slower computer takes longer. When the model is not available, all trackers still work. Only the AI functions
say "The assistant is not available now".

**NVIDIA GPU**: to run the model server on the GPU, put `COMPOSE_FILE=compose.yaml:compose.gpu.yaml` in `.env`.
You need the NVIDIA Container Toolkit with CDI. Tested on arm64.

**Use another model server.** Any server with an OpenAI-compatible `/v1/chat/completions` endpoint works (for
example a llama.cpp or vLLM server with a GPU). Open **Settings > AI model**, enter the server URL (ending in
`/v1`), the model name and the key if the server needs one. Select **Save**, then **Test connection**. These
settings are per family. The defaults come from `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` in `.env`. The model
must support JSON schema output (`response_format`), as llama.cpp does.

## Day and night plan

**Assistant > Sleep plan** shows one typical 24 hours for your child as a timeline from the morning: sleep blocks
(each nap and the night sleep, with a start and an end) and the feeds of the day and of the night. The app
calculates the plan. The AI model does not make the times.

- **The start point is your child's own logs** of the last 14 days. Each time is the middle value (the median) of
  those days, so one unusual day does not change the plan. Sleep data has a long tail: some nights are very
  different, and they must not move the plan.
- **From 5 complete days, the start point is only your child's times.** With 1 to 4 days the plan mixes them with
  typical times for the age, and it says so on each row. With no logs it shows typical times for the age.
- **Small steps toward best practice.** The plan uses the three bands of the National Sleep Foundation for the
  age: recommended, "may be appropriate" (the experts did not agree), and not recommended. The page says what
  changed and why ("Steps and checks in this plan"). The next plan starts from the new logs. So the plan follows
  what your family really does, and it does not make large changes.

  | The logs show | The plan |
  |---|---|
  | Less sleep than "may be appropriate" | Adds a quarter of the gap, from 15 to 60 minutes. Says to speak to a doctor or nurse |
  | Less than recommended, inside "may be appropriate" | Adds 15 minutes |
  | Inside the recommended range | No change |
  | More than recommended, inside "may be appropriate" | No change, one note |
  | More than "may be appropriate" | No change. Says to check the logs for a timer that was not stopped, then to speak to a doctor or nurse, with the warning signs |

  Added sleep goes to bedtime first (20 minutes earlier at most in one plan), then to the naps.
- **Sleep is never cut.** No study shows harm from long sleep in children under 5, and no source says to cut the
  sleep of a healthy child. Long sleep can be a sign of illness, so the page says to get the child checked.
- **Naps from 2 years.** When a nap is longer than 2 hours or ends after 15:00, and the night sleep starts after
  20:30 or is shorter than 10 hours, the plan ends the nap 15 minutes earlier (Thorpe 2015; Raising Children
  Network).
- **Number of naps.** The page shows your child's number next to the typical number for the age. The plan takes
  no step toward it: no source recommends a number of naps.
- **Feeds for a young baby.** When the logs of a baby younger than 3 months show fewer than 8 feeds in 24 hours,
  the plan adds 1 feed in the longest time between two feeds. In the first 4 weeks it also adds a feed when more
  than about 4 hours pass at night.
- **A baby younger than 12 weeks** has no fixed day and night yet. The plan takes the baby's usual number of
  sleeps in a day and puts them at the times of the day at which the baby sleeps most often. When the logs show too
  little sleep, the plan adds one new sleep block in the longest time with no sleep. A young baby whose logs show a
  night of 8 hours or more gets naps and a night block.
- **A fit check.** The calculator knows two patterns: naps with a night, and (a young baby) sleeps round the
  clock. When the logs do not fit (for example the app finds no night sleep, or the number of naps is different
  each day), the page says so. The plan is then a rough guide, and it takes no steps.
- **The app counts only what is logged.** If you do not log each sleep and each feed, the plan sees too little
  and makes steps that are not necessary. Log them, and the plan needs fewer changes.
- **Your child's numbers** (sleep in 24 hours, sleep at night, wakes and feeds at night) show next to the range
  that is common for the age. Children differ a lot: the common range is information. The steps of the plan use
  only the recommended ranges of the guideline bodies.
- **The rules change with the age**, in 7 age bands from birth to 5 years. For example: the change from 2 naps to
  1, and "nap on some days" from about 3 years.
- **Advice from the assistant** is optional. The AI model gets the calculated plan and writes a short summary and
  tips with sources. It cannot change the times.
- **API and MCP**: `GET /api/v1/children/{id}/sleep/regime` and the MCP tool `get_day_and_night_plan`.

Where the numbers for the age come from (the app stores the numbers and a link, not the text of the papers):

| What | Source |
|---|---|
| Wake time, naps, wake windows, bedtime, longest sleep at night, to 24 months | The sleep norms file (Liu et al. 2019, see below) |
| Night wakes by age, with the 10th and 90th percentile | Paavonen et al. 2020, Sleep Medicine 69:145-154 |
| Night feeds at 6 to 12 months | Brown and Harries 2015, Breastfeeding Medicine 10:246-252 |
| Total sleep by age, with the reference range | Galland et al. 2012, Sleep Medicine Reviews 16:213-222 |
| Bedtime and wake time from 2 years, with limits | Blair et al. 2012, Sleep 35:353-360 |
| Naps and night sleep from 2 years | Iglowstein et al. 2003, Pediatrics 111:302-307; Staton et al. 2020, Sleep Medicine Reviews 50:101247 |
| Sleep in 24 hours: recommended, may be appropriate, not recommended (the steps use these) | National Sleep Foundation 2015 (Hirshkowitz et al.), Table 2 |
| Feeds in 24 hours for a young baby | CDC, How Much and How Often to Breastfeed |

No published numbers exist for these, so only your child's own logs decide them: wake windows from 2 years, the
number of night feeds before 6 months, the time to stop a night feed, and the time to drop a nap. Night wakes
that a device measures (about 4 a night at 2 to 5 years) are not the same as wakes that a parent sees (about 1),
so the app uses only numbers from parent reports.

The file with the numbers is `src/frecklebubby/data/sleep_regime.json`. The calculation is in
`src/frecklebubby/services/regime.py`.

## Sleep model

The Home screen shows the next nap or bedtime. With the bundled **sleep norms file** it uses your child's last 14 days and typical patterns of babies of the same
age, and it shows an 80 % range ("earliest" to "latest"). Insights then also show the current nap stage (for example
"Mostly 3 naps a day"), compare total sleep with babies of the same age, and show a card when a nap change is common
at this age. The recommended sleep ranges (AASM 2016, NSF 2015) stay the main reference.

- **What it is**: a JSON file with sleep percentiles by age (0 to 24 months) and the settings of the predictor. It
  has no data about single babies.
- **Where it comes from**: made with `training/sleep/` from the infant-sleep data of Liu et al. (2019),
  "Time-Series Analysis via Low-Rank Matrix Factorization Applied to Infant-Sleep Data"
  (<https://arxiv.org/abs/1904.04780>): 700 babies whose parents logged sleep in the Baby Connect app. On babies
  not used to make the file, the start of the next sleep was within 30 minutes 53 % of the time (old table 49 %);
  the median error was 27 minutes (old table 32 minutes). How to make the file: `training/sleep/README.md`.
- **Licence**: the data is open for non-commercial use with attribution to Liu et al. The norms file
  (`src/frecklebubby/data/sleep_norms.json`) and the data file (`training/sleep/data/`) have the same terms.
- **Your own file**: put `sleep_norms.json` in the data folder (`DATA_DIR/sleep_norms.json`; in the container
  `/data`, the `data` volume), or set `SLEEP_NORMS_PATH` to its full path. It replaces the bundled file. Restart is
  not necessary.
- **Fallback**: a table of common wake windows by age (`src/frecklebubby/data/wake_windows.json`). The app uses it
  when the file is missing or not valid, or the child is older than 24 months, or no night sleep is
  logged in the last 24 hours, the app uses the wake-window table as before.

## Voice commands

You can log things and ask questions with your voice. The words go to the assistant, the same as typed words:
"wet nappy", "she had 120 ml of formula", "start a nap", "how long can she stay awake?".

- **Talk button** (microphone, next to "Tell me what happened" on Home and next to the question box in the
  Assistant): tap, say your words, tap again.
- **Hands free** (wave button, next to the microphone): the app listens. Say **"Hey Bubby"** or **"OK Bubby"** and
  then your words. A short sound tells you that the app heard the keyword. You can also say the keyword, wait for
  the sound, and then say your words.
- **Hold-to-talk button on the side** (Settings > Voice): a large see-through button on the left or right side of
  the screen, at the height you select, on all pages. Hold it down, say your words, and let go. It is for use with
  one hand.
- **Read the answer aloud** (Settings > Voice): off, for hands free only, or for all voice commands. The answer
  always shows on the screen too. The voice is the voice of your phone or browser.

A voice command **saves the entries immediately**, because you have no hand free to confirm. When the app is not
sure (for example the amount was not in your words), the entry is saved with the text "Not sure: …". You can undo
it in the voice card or in the Assistant, and you can change or delete each entry in the timeline. An exact copy
of another item in the same command is not saved.

**Limits of hands free.** A web app can listen only while the app is open and the screen is on. With hands free on,
the app keeps the screen on, so connect the phone to power for long use. Hands free stops when you lock the phone
or go to another app.

**Privacy.** The speech-to-text model (Whisper) runs on your own server, on the CPU. No audio goes to a third
party. With hands free on, the phone finds each spoken phrase and sends it to your server for the keyword check.
When the phrase does not start with the keyword, the server gives back no text. The server does not store or log
the sound or the text. Read aloud uses the speech voice of the device; some browsers use an online voice.

**Server settings** (`.env`):

- `VOICE=false` removes the voice buttons.
- `WHISPER_MODEL` (default `small.en`, about 500 MB, about 1 second for a command on a modern CPU). The first start
  downloads the model to `DATA_DIR/models/whisper`. `base.en` is faster and makes more errors.
- Other languages: `WHISPER_MODEL=small` and `WHISPER_LANGUAGE=` (empty). The keyword and the assistant are English.
- `LIMIT_VOICE` (default `300/300`): recordings per user in a time window.
- **Without containers**: install the extra (`uv sync --extra voice`).
- **Microphone**: browsers give the microphone only to HTTPS pages (or `localhost`). See [HTTPS](https.md#https).

API: `POST /api/v1/voice/transcribe` (a WAV file: one channel, 16 bit, 16 kHz, 30 seconds maximum; form field
`wake=true` for the keyword check) gives `{"heard", "text"}`. `POST .../assistant/chat` takes `"voice": true`.

## Cry helper

The **Crying?** tile on the Home screen answers "what do I check first?".

- **Just tell me what to check**: uses only the logs (last feed, last sleep, last nappy, age). It ranks the likely
  needs, gives things to try and says when to get medical help. Each fact has a source from the built-in NHS and CDC
  library. This part needs no model and no microphone.
- **Listen**: records up to 60 seconds and adds a guess from the sound. The audio is analysed on your server and is
  not stored.
- You can save the crying time and what helped to the timeline. Reports show crying per day.

**The sound guess is experimental. It is a guess, not a diagnosis.** There are two models:

- **Cry detector**: finds crying and snoring in the recording. On the test recordings of its dataset it found 40 of
  43 clips with a cry and gave no false alarm on 39 clips without one.
- **Cry reason** (hungry, tired, burping, belly pain, discomfort, scared): trained on 489 clips where the label is
  the parent's own guess, and 382 of them say "hungry". On babies the model had not heard it was right 80 % of the
  time; "always hungry" is right 78 % of the time. Thus the logs decide the order of the list, and the sound guess
  is shown only as a hint. The app reads these numbers from `model_card.json` and shows them to the parent.

The model files are bundled in `src/frecklebubby/data/models/cry/`. They are for **non-commercial use, with
attribution** (ICSD is CC BY-NC-SA 4.0; see `NOTICE.txt` in that folder). Without the files, or without the `cry`
extra, the app says "Sound analysis is not installed on this server." and the rest works.

- **Make the files again**: `training/cry/README.md`. You need the ICSD dataset and the DeepInfant clips.
- **Your own models**: put `cry_detector.onnx`, `cry_reason.onnx`, `model_card.json` and `NOTICE.txt` in
  `DATA_DIR/models/cry` (in the container `/data/models/cry`, the `data` volume), or set `CRY_MODEL_DIR`. They
  replace the bundled models.
- **Without containers**: install the extra (`uv sync --extra cry`) and the `ffmpeg` program. The container image has
  both.
- **Microphone**: browsers give the microphone only to HTTPS pages (or `localhost`). See [HTTPS](https.md#https).

## Knowledge library and licences

The assistant answers from these sources and shows each source it used:

- **Built-in library** (`src/frecklebubby/data/library/`): pages from the NHS and the CDC.
  - NHS pages: Contains public sector information licensed under the Open Government Licence v3.0.
  - CDC pages: Material developed by CDC. Public domain; reference does not imply endorsement by CDC or the U.S.
    Government. Available free at cdc.gov.
  - CDC "Learn the Signs. Act Early." milestone checklists (public domain), with the same notice.
  - The app changed gendered pronouns for the child to they, them and their in this text. It made no other change.
- **Trusted sources (links only)**: for example Raising Children Network, Red Nose, healthdirect, AAP and
  well-known sleep books. Frecklebubby stores only the title and the link, not their text.
- **WHO growth data** (`src/frecklebubby/data/growth/`): WHO Child Growth Standards, World Health Organization,
  2006. WHO allows use for non-commercial purposes with acknowledgment of WHO as the source. If you use
  Frecklebubby commercially, get written permission from WHO. WHO does not endorse Frecklebubby. See
  `src/frecklebubby/data/growth/NOTICE.md`.
- **Your uploads**: in **Settings > Knowledge sources** you can add PDF, EPUB, text or Markdown files (up to
  50 MB), for example notes from your doctor. Only your family can use them. You can delete them.
- **Web lookup** (off by default): in **Settings > AI model** you can let the assistant read pages from an approved
  list of medical websites. The same page shows the list. Pages are kept for 7 days.

#### Change the approved websites

The person who runs the server sets the list. A user cannot change it in the app. The assistant does not search the
web: it reads only the pages in a fixed list, and only from the approved websites.

1. Add or remove the website in `src/frecklebubby/data/web_allowlist.txt`. Write one host name on each line,
   for example `www.rch.org.au`. Do not write `https://` or a path. `example.org` and `www.example.org` are two
   different hosts.
2. Add or remove the pages in `src/frecklebubby/data/sources.yaml`. Each page is one item with `kind: web`:

   ```yaml
   - id: rch-fever
     title: Fever in children
     publisher: The Royal Children's Hospital Melbourne
     year: 2025
     url: https://www.rch.org.au/kidsinfo/fact_sheets/Fever_in_children/
     kind: web
     topics:
     - fever
     summary: One or two sentences that say what the page tells a parent.
   ```

   The `id` must be new. The `url` must start with `https://` and its host must be in `web_allowlist.txt`.
   The assistant selects a page when the question shares words with its `topics`, `title` or `summary`.
3. Build the app again and restart it: `docker compose build app && docker compose up -d`.

Add only websites you trust for medical facts, such as a health department or a children's hospital. The assistant
gives the text of these pages to parents as a source.

If a question is not covered by the sources, the assistant says so. It then lists up to three trusted pages on the
topic as links. This list comes from the source list by fixed rules, not from the model. Urgent warnings (for
example a fever in a baby under 3 months) come from fixed rules, not from the model, and always show first.
