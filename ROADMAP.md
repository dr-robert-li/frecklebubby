# Roadmap

This file lists the work that is planned, and the state of work that is in progress. The order is the planned order.
Released work is in [CHANGELOG.md](CHANGELOG.md).

State on 23 November 2026:

| Item | State |
|---|---|
| 1. Localisation, first language: Simplified Chinese | Not started. Two decisions are open. |
| 2. Cry recordings as a labelled dataset | The app part is released (0.9.0). The plug-in runs on the server of the owner. The training pipeline is not started. |
| 3. Tablet Mode: a wide layout for large screens | Not started. Three decisions are open. |

## 1. Localisation, first language: Simplified Chinese

The app text, the assistant and the voice commands in more than one language. Simplified Chinese is first.

Findings of a test on 22 November 2026 (six spoken commands from a synthetic Mandarin voice):

- The voice model of today, `small.en`, is English only. It cannot write Chinese.
- The multilingual model `small` writes Chinese in about 1 second for a command, and English stays correct.
  It has the same size (about 500 MB).
- The keyword "Hey Bubby" inside Chinese speech was not recognised. Chinese needs its own keyword.
- The model writes traditional characters unless the prompt is in simplified characters. A conversion step
  after the model makes the result certain.
- Some words came out as other words with the same sound. The larger model made nearly the same errors, so
  the test voice is a likely cause.

To do:

- Change the default voice model to `small`. Send the language of the user with each recording, with a prompt
  and a keyword for each language.
- Tell the read-aloud voice of the device which language to use.
- Test the assistant model in Chinese (logging from plain words, answers with sources).
- Translate the app text. Decide what to do with the knowledge library, which is in English.

Open decisions:

- The Chinese keyword. It must be words that a parent does not say to the child.
- A test with 5 to 10 commands from a real Mandarin speaker, before the build.

## 2. Cry recordings as a labelled dataset for model training

Keep the recordings of the cry helper, with their labels, so that they can be added to the existing training
data (ICSD and DeepInfant) and the sound models can be trained again.

### Done

- **In this repository (released in 0.9.0):** a general extension point for plug-ins (`src/frecklebubby/plugins.py`,
  see [Development](docs/development.md#plug-ins)), the limit of 10 seconds for a recording, and a test that the app
  with no plug-in keeps no audio.
- **In the closed repository:** the plug-in. It runs on the server of the owner (my.frecklebubby.app) since
  23 November 2026, in a private image: the open image of the release, plus the plug-in. It was tested there with a
  real recording: the message, the save, the label and the delete.

What the plug-in does:

- It holds a recording in memory for 10 minutes after the analysis. It writes the clip to the disk only when the
  parent saves the crying entry from the cry helper. A crying entry that is typed in gets no clip.
- It stores one lossless file for each entry, with the label: the reason that the parent selected (as it is), if
  the parent changed the default reason, what helped, the guesses of the helper and of the sound model, the seconds
  of crying that the detector found, the age in days, and the time since the last feed and the last sleep. The label
  has no name and no date of birth.
- It keeps a clip also when the detector finds no crying, because the detector can miss a real cry.
- It deletes the clip when its entry, its child or its family is deleted.
- The owner of each family gets a message one time. A checkbox in **Settings > Options of this server** is on by
  default. After an opt out, no new clip is kept, and the clips from before stay. A carer gets no message.
- The operator can export all clips and one table of labels as a zip file.
- The [privacy policy](https://frecklebubby.app/privacy.html#cry) of the hosted server tells the parent what is
  kept, for what purpose, who can get it, for how long and how to turn it off.

### To build (in the closed repository): the training and publishing pipeline

It runs by hand on the machine of the owner, not as a service. It needs real clips first.

- Read the export of the plug-in in the training kit (`training/cry`). Map the reasons of the parent to the classes
  of the model: the helper has 10 reasons, the model has 6 classes, and "wind" can be burping or belly pain.
- Train with each child as one group, so that a child is not in the training data and the test data at the same
  time. Give more weight to a label that the parent changed from the default: a model must not learn its own guesses.
- Use the seconds of crying in the label to filter the clips where the detector found no crying.
- Ignore the time since the last feed or sleep when it is not plausible. A family can log feeds and sleep in a
  different app.
- Look at the free text "what helped" before it is published, because it can contain a name.
- Publish the dataset with restricted access (a gated dataset on Hugging Face): a person requests access, and the
  owner gives or refuses permission. It contains only the new clips. The other datasets are named as sources.
- At each update of the dataset, remove the clips that were deleted on the server.
- The trained model can be published and included in the open source app.

### Decided

- **The open source app does not keep or send recordings.** The code that keeps the clips, and the training
  pipeline, are in a closed repository. Only the server of the owner uses it. The reason: another person who hosts
  the app must not get a ready tool to collect recordings, because that person can treat the data with less care.
- **The value is in the dataset and the trained model, not in the recorder.** A closed repository does not stop
  another person who writes a recorder. This is accepted.
- **The licence of the app (AGPL-3.0) helps here.** The owner has the copyright and can run a closed plug-in.
  Another person who hosts a changed app for other people must publish the changes.
- **The new clips go on top of the existing dataset.** They do not replace it.
- **A plug-in in the same image, not a second network service.** Then a recording does not go across a network
  before the export, and there is no second sign-in to protect.

### Open decisions

- **The licence of the model.** A fact for that decision: ICSD is CC BY-NC-SA 4.0, so a model that is trained with
  it is limited to non-commercial use.

## 3. Tablet Mode: a wide layout for large screens

The app is one column of 520 px on all screens today. On a tablet in landscape, a laptop or a desktop computer,
most of the screen is empty. Tablet Mode uses that room to show more information at one time.

Decided:

- **Two uses, in two steps.** Step 1 is the wide layout for normal use: the same tasks as on the phone, with more
  in view. Step 2 is a dashboard view for a tablet that stands in the nursery or the kitchen and is always on.
- **Automatic by the width of the window, with a setting to turn it off.** A window that is wide enough gets the
  wide layout. A phone, and a tablet in portrait, keep the layout of today. A person can force the phone layout in
  **Settings > Appearance**.
- **The bottom bar stays.** The navigation is the same in each mode, so that the app is familiar. There is no side
  bar.
- **The Home screen shows panels next to the tiles and the timers.** The panels are:
  - the timeline of today,
  - the day and night plan,
  - the insights and the week pattern,
  - the assistant.
- **The user selects the panels.** Each panel can be shown or hidden.
- **Each other screen gets a wide layout too:** History, Reports, the assistant, Notifications and Settings. For
  example, History shows the week and the selected day side by side.

To do, step 1 (the wide layout):

- Find the width at which the wide layout starts. Test on an iPad in landscape and in portrait, on a small laptop
  and with a split window.
- Home: the tiles and the timers stay in one column of the present width, and the panels fill the other room.
  The panels are the components that the app has today, used again.
- The setting for the panels, and the setting that forces the phone layout.
- A wide layout for each other screen. Charts and tables get the full width.
- Touch targets, keyboard use and screen reader order stay correct in the wide layout.
- Playwright tests at a tablet size and at a desktop size, and new screenshots for the docs and the landing page.

To do, step 2 (the dashboard view):

- A view with large text that a person can read from a distance: the timers that run, the time since the last
  feed, nappy and sleep, and the next sleep of the plan.
- The screen stays on (the Screen Wake Lock function of the browser), and the data updates with no touch.
- A dark variant for the night, so that the screen does not light the room.

Open decisions:

- **Where the panel selection is kept.** For each device (recommended: a phone and a tablet of the same person
  need different values) or for each user.
- **The sign-in of a shared tablet.** A dashboard on a wall is signed in as one carer. Decide if the dashboard view
  can log entries, or only shows data. Each entry has the name of the person who made it.
- **The assistant panel on Home.** Decide if it is the full chat or only a field for a question, with the answer
  on the assistant screen.
