# The Drum Looper

A customizable, screen-reader-first drum machine built into the app. It works out of the
box with a **built-in synth kit** (no files needed), and you can load **your own drum
libraries** for higher-fidelity sounds.

## Quick start

1. Open the **Drum Looper** tab.
2. Leave **Kit** on "Synth (built-in)", pick a **Groove**, set the **Tempo**, and press
   **Start**.
3. To customize, choose a part under **Edit part** (Kick, Snare, …) and toggle its steps.
   Use **Mute this part** to silence a part without erasing its steps.

The loop keeps playing while you switch to other tabs, so you can jam over it while editing
a tone. Press **Stop** (or close the app) to end it.

## The controls

| Control | What it does |
|---------|--------------|
| **Kit** | The sound set: "Synth (built-in)", any kit folder found in `Samples/`, or "Browse for a kit folder…". |
| **Groove** | A starting pattern. Picking one loads its meter and steps; edit from there. |
| **Beats per bar** / **Beat unit** | The time signature (e.g. 7 and 8 = 7/8). See odd meters below. |
| **Grid (steps per beat)** | How finely each beat is divided: Quarter, Eighth, Triplet, or Sixteenth. More steps = finer placement. |
| **Bars in loop** | How many bars the loop spans (1–4), for phrases longer than one bar. |
| **Tempo** | 30–300 BPM. (A screen reader announces the real BPM, not a percentage.) |
| **Edit part** + **Steps** | Pick a part, then toggle its step checkboxes. Steps are labelled by beat (e.g. "Beat 3", "Beat 3.2", "Bar 2 Beat 1") so odd meters stay easy to navigate. |
| **Mute this part** | Silences the selected part without erasing its steps. |
| **Start / Stop** | Begins/ends the loop. Edits while playing take effect on the next loop. |

## Odd & prog time signatures

Set **Beats per bar** and **Beat unit** to anything you like — 5/4, 7/8, 9/8, 6/8, 5/8,
and so on. The step grid resizes to fit the meter, and the steps stay labelled by beat so
you always know where you are.

Because the whole loop is one repeating unit, an **odd-length loop naturally cycles against
your playing** — the "lands outside the bar" feel of bands like Meshuggah or Tool. For a
tight djent-style polymeter, try a short loop like **7/16** (Beat unit 16, 7 beats) over a
straight 4/4 pulse. Built-in odd grooves to start from: **5/4, 7/8 (2+2+3), 6/8, 5/8 (3+2),
and Djent 7/16 (poly)**.

Tip: the **Metronome** tab has a matching **Accent grouping** field (e.g. `2+2+3` for a 7)
so its click accents the groups the same way.

## Bringing your own kit

A kit is a **folder** whose subfolders are named for drum parts, each holding one or more
`.wav` files. The looper loads the first working sample it finds in each part folder.

```
My Kit/
├── KICK/      kick_01.wav, kick_02.wav, ...
├── SNARE/     snare.wav
├── HIHAT/     closed_hat.wav
├── OPENHAT/   open_hat.wav
├── CLAP/      clap.wav
├── PERC/      perc.wav
├── 808/       808_C.wav
└── FX/        riser.wav
```

Recognised part-folder names (case-insensitive):

| Part | Folder names accepted |
|------|-----------------------|
| Kick | `KICK`, `KICKS` |
| Snare | `SNARE`, `SNARES`, `SNAP` |
| Hi-hat (closed) | `HIHAT`, `HAT`, `HATS`, `CH`, `CLOSEDHAT` |
| Open hat | `OPENHAT`, `OH`, `OPEN` |
| Clap | `CLAP`, `CLAPS` |
| Perc | `PERC`, `PERCUSSION` |
| 808 / sub | `808`, `808S`, `BASS`, `SUB` |
| Tom | `TOM`, `TOMS` |
| Ride | `RIDE` |
| Crash | `CRASH`, `CYMBAL` |
| FX | `FX` |

A **flat folder** also works if the files themselves are named for the parts
(`kick.wav`, `snare.wav`, `hihat.wav`, …).

### Where to put kits

- Drop kit folders into the **`Samples/`** folder in the app directory — they appear in
  the **Kit** dropdown automatically.
- Or press **Kit → "Browse for a kit folder…"** and pick any folder anywhere. The app
  remembers where your kits live.

### Formats

Any standard `.wav` works — 16/24/32-bit integer or 32/64-bit float, mono or stereo, any
sample rate. The app converts everything to a common format internally. Very long samples
are trimmed to a few seconds.

## Timing — why samples always land on the beat

Samples are different lengths (a clap is short, an 808 rings out), so the looper never
relies on sample length for timing. It **pre-mixes** the whole loop: each hit's audio is
placed at the exact sample position of its beat, parts are summed together, and anything
ringing past the end wraps around to the start. The result loops seamlessly and every
hit's attack is exactly on the meter, no matter how long the sample is.

## Licensing note

Third-party drum kits are often copyrighted. Keep your own kits **local** — the app loads
them from your machine and never uploads or redistributes them. This project ships only
the synthesized kit (which it generates in code) and does **not** bundle any third-party
samples. The `Samples/` folder is git-ignored for exactly this reason.
