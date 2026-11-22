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

- **The setting is on by default.** A family can turn it off (opt out).
- **A recording is 10 seconds at most.** The app already records 10 seconds. The server accepts up to 60
  seconds through the API today; this limit goes down to 10 seconds.
- **The new clips go on top of the existing dataset.** They do not replace it.
- **The model stays open weight.** It can be published on Hugging Face.
- **The dataset has restricted access.** It can be stored on Hugging Face as a gated dataset: a person requests
  access, and the owner gives or refuses permission.

To build:

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
- Tell each family clearly, at the first use of Listen and in Settings, that recordings are kept and how to
  turn this off. Change the privacy text in the app and in the docs, which now say that audio is not stored.

Open decisions:

- **Upload to Hugging Face.** To keep a recording on the family's own server is one thing. To send it to
  Hugging Face is to give it to a third party. Recommendation: a second, separate agreement of each family
  before its clips are uploaded.
- **What the published dataset contains.** The existing data has its own licences (ICSD is CC BY-NC-SA 4.0).
  Recommendation: publish only the new clips, and name the other datasets as sources.
- **Licence of the model.** A model trained with the existing data stays for non-commercial use.
