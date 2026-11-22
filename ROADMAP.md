# Roadmap

This file lists the work that is planned and not started. The order is the planned order.
Released work is in [CHANGELOG.md](CHANGELOG.md).

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

Decided:

- **The open source app does not keep or send recordings.** All data stays on the server, as today. The code
  that keeps the clips, and the training pipeline, are not in this repository.
- **The recording and training pipeline is in a closed repository.** Only the server of the owner
  (my.frecklebubby.app) uses it. The reason: another person who hosts the app must not get a ready tool to
  collect recordings, because that person can treat the data with less care.
- **The value is in the dataset and the trained model, not in the recorder.** A closed repository does not stop
  another person who writes a recorder. This is accepted.
- **The model can be open.** The trained model can be published and included in the open source app. Only the
  recordings and the pipeline stay closed.
- **One setting for the parent, only when the pipeline is connected.** A checkbox in Settings. It is on by
  default, and a parent can turn it off (opt out). The same page tells the parent what is kept, for what purpose,
  for how long, who can get access, and how to delete it. With no pipeline, the checkbox does not show.
- **A recording is 10 seconds at most.** The app already records 10 seconds. The server accepts up to 60
  seconds through the API today; this limit goes down to 10 seconds.
- **The new clips go on top of the existing dataset.** They do not replace it.
- **The model can be published** on Hugging Face. Its licence is decided later (see the open decisions).
- **The dataset has restricted access.** It can be stored on Hugging Face as a gated dataset: a person requests
  access, and the owner gives or refuses permission.

How the two parts connect (decided, not built):

- This repository gets one small, general extension point: the app loads extra Python packages that are installed
  with it (a plug-in), and a plug-in can add a setting and get the recording when a crying entry is saved. The
  extension point has no code for recordings, storage or upload.
- The closed repository has two parts. Part 1 is a plug-in: it keeps the clips and the labels on the same server,
  adds the checkbox and the disclosure text, and makes the export. Part 2 is the training and publishing pipeline:
  it runs by hand on the machine of the owner, not as a service.
- The server of the owner runs a private image: the open image of the release, plus the plug-in. Not a second
  network service: then a recording does not go across a network before the export, and there is no second
  sign-in to protect.
- The README tells the reader that the hosted server keeps cry recordings (with opt out) and that the open
  source app does not.

To build (in the closed repository, except where this text says other):

- Keep the clip only when the parent saves the crying entry. The server holds the recording for some minutes
  after the analysis and deletes it when the parent does not save.
- Store one lossless file for each entry in the data folder, with the label: the reason that the parent
  selected, what helped, the guess of the sound model, the age in days, and the time since the last feed and
  the last sleep.
- Store the reason of the parent as it is. Map it to the classes of the model at training time: the helper has
  10 reasons, the model has 6 classes, and "wind" can be burping or belly pain.
- Record if the parent changed the default reason. The default is the first guess of the helper, and a model
  must not learn its own guesses.
- Delete the clip when its entry is deleted, and all clips when the family is deleted.
- An export for the owner: a zip file with the clips and one table of labels, in the format that
  `training/cry` reads. In training, each child is one group, so that a child is not in the training data and
  the test data at the same time.
- Tell the owner of each family clearly, with the message at sign-in and in Settings, that recordings are kept
  and how to turn this off. The privacy text of the open source app stays true (audio is not stored); the plug-in changes
  the text on the server of the owner.
- In this repository: the extension point, the lower limit of 10 seconds, and a test that the app with no
  plug-in keeps no audio.

Decided on the message and the dataset:

- **A message at the first sign-in.** The first user of a family (the owner) gets a message one time, at the
  first sign-in. When the plug-in is connected after the family exists, the message shows one time at the next
  sign-in. The message shows only when the plug-in is connected, so an open source server with no plug-in never
  shows it. It is a message only: it tells the parent that the clips are kept and uploaded to the gated dataset
  on Hugging Face, and where to turn this off. It has no button to refuse.
- **On by default, opt out in Settings.** To opt out, the parent goes to Settings and clears the checkbox.
- **The published dataset contains only the new clips.** The other datasets (ICSD, DeepInfant) are named as
  sources. Access is by permission only: a person requests access, and the owner gives or refuses it. The
  dataset is not open.
- **A family that opts out later.** The clips that are kept before the opt out stay. No new clip is kept after
  the opt out.
- **The message goes to the owner only.** A carer who joins later does not get the message, also not at the
  first use of Listen. The disclosure stays on the Settings page.

Open decisions:

- **The licence of the model.** To be decided later. A fact for that decision: ICSD is CC BY-NC-SA 4.0, so a
  model that is trained with it is limited to non-commercial use.
