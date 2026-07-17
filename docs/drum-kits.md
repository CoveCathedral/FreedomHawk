# The Drum Looper

A customizable, screen-reader-first drum machine built into the app. It works out of the
box with a **built-in synth kit** (no files needed), and you can load **your own drum
libraries** for higher-fidelity sounds.

## Quick start

1. Open the **Drum Looper** tab.
2. Leave **Kit** on "Synth (built-in)", pick a **Groove** (200 built in — basics plus
   generated variations, many with drum fills), set the **Tempo**, and press **Start**.
3. To customize a groove, press **Edit Pattern…** — see the Pattern Editor below.
4. Use **Part** + **Mute this part** to silence a part live without erasing its steps.

The loop keeps playing while you switch to other tabs, so you can jam over it while editing
a tone. Press **Stop** (or close the app) to end it.

## The main tab

| Control | What it does |
|---------|--------------|
| **Kit** | The sound set: "Synth (built-in)" plus any kit folder found in `Samples/`. Arrowing through this list only switches kits — it never opens a dialog. |
| **Import Drum Kit…** | A separate button that opens the folder picker to load a kit from anywhere. The app remembers where your kits live. |
| **Category** | Filters the Groove list by genre family (Rock, Funk, Trap, 5/4…) — plus any categories you create when saving your own patterns. |
| **Groove** | 200 built-in patterns (the classic bases plus numbered variations — names ending in "fill" include a drum fill), followed by **your saved patterns** shown with their category. First-letter navigation works in the list. |
| **Fill every** | For jamming: stretches the groove so the fill only comes around every 2, 4, 8, 12, or 16 bars — plain groove until then, fill as the turnaround, crash on the restart. "Pattern length" plays the groove exactly as written. |
| **Fill style** | "As written" plays the groove's own fill. **"Improvised"** generates fresh fills on every render — varying length (short, long, occasionally a whole bar) and density, Diablo-style rule-bound randomness — so the groove rarely repeats itself exactly. Fills follow the **Fill every** cadence (a 4-bar cycle when it's unset) and always land on the meter, odd time signatures included. |
| **Tempo** | 30–300 BPM. (A screen reader announces the real BPM, not a percentage.) |
| **Drum volume** | Master volume for the drums (0–100%), so they sit right against your guitar. |
| **Part** + **Mute this part** | Pick a part and mute/unmute it live, without touching its steps. |
| **Edit Pattern…** | Opens the Pattern Editor dialog. |
| **Kit Sounds…** | Choose which sample each part uses (sample kits only — the synth kit's sounds are fixed). See below. |
| **Start / Stop** | Begins/ends the loop. Changes while playing take effect on the next loop. |

## The Pattern Editor (Edit Pattern… — or Ctrl+D from anywhere)

A tracker-style grid built for keyboard-and-ears editing. One list line per **drum
line** ("Kick: 4 hits, sample Kick ;P") — and lines are free: **stack several of the
same drum** and **mix samples from different libraries** in one pattern (synth kick,
Bloodlust snare, a friend's crash), up to 24 lines. A shared **time cursor** lives on
the arrow keys — every move is **spoken directly through your screen reader** ("Bar 2,
Beat 3.2, hit"):

| Key | Action |
|-----|--------|
| **Up / Down** | Move between lines (spoken: the line, then the cursor's state on it). |
| **Left / Right** | Move the cursor by one grid step — the smallest increment. |
| **Ctrl + Left / Right** | Move by one beat. |
| **Ctrl + Shift + Left / Right** | Move by one bar. |
| **Home / End** | Jump to the start / last step. |
| **Space** | Cycle the step's state: **on → accent → ghost → off**, each spoken ("Kick accent, Beat 2"). Accents hit harder, ghosts whisper — real drummer dynamics. Dynamics survive saving, sharing, and MIDI (as note velocities) in both directions. |
| **Enter** | Sample options for this line: any sample from its kit folder, the automatic default, or **None** (silence the line). |
| **Delete** | Remove the selected line. |
| **P** | Preview this line's sound. |
| **F1** | Speak this key list. |

Buttons (all a Tab away):

- **Add Line…** — add another line: pick the part (Kick, Snare, …), the source (the
  synth, or **any kit library you have**), and the sample. This is how you stack drums
  and mix libraries.
- **Load Groove…** — replace the editor contents with any built-in or saved pattern.
- **Save as Preset…** — name the pattern, put it in a category (existing or a **new one
  you type**), and it appears in the main tab's Groove list permanently.
- **Play/Pause** auditions the loop while you edit (changes heard on the next loop);
  **Save** keeps everything; **Cancel** or Escape discards.

**Ctrl+D** anywhere in the app opens a fresh, empty editor on the Drum Looper tab —
build a pattern from scratch mid-session, save it as a preset, jam on.

## The Tools menu: library, sharing, MIDI

The main **Tools** menu (Alt+T) holds the sequencer's management and sharing commands:

| Command | What it does |
|---------|--------------|
| **Drum Pattern Editor… (Ctrl+D)** | Opens a blank editor. |
| **Drum Pattern Library…** | Manage your saved patterns: rename or delete a pattern, move it to another category, or rename a whole category at once. Built-in grooves are permanent and not listed. |
| **Export Drum Loop as WAV…** | Renders the current loop exactly as it plays — mutes, fill cadence, improvised fills, volume — to a `.wav` you can drop in a DAW, record over, or share. |
| **Export / Import Drum Pattern…** | Patterns as small shareable files (`.fhdrum.json`) — trade grooves with other users. Imports land in the "Imported" category (or the one the file names) and become the current groove. |
| **Export Pattern as MIDI…** | The pattern as a standard `.mid` file on the General MIDI drum channel — opens in any DAW with any drum sounds, meter included (odd meters too). |
| **Import MIDI File…** | Reads a `.mid` file's drum notes (General MIDI mapping, quantized to the grid, up to 4 bars) and **opens it straight in the Pattern Editor** — press Play to hear it, tweak it, then Save to make it the current groove or Save as Preset to keep it. The import summary is spoken as the editor opens. |

MIDI *controller* input (crafting beats from a MIDI keyboard) is planned.

The time signature also lives here: **Beats per bar**, **Beat unit**, **Grid** (how finely
each beat divides), and **Bars in loop** (1–4). **Growing the bar count repeats the
existing music across the new bars** (no silent gaps — edit the copies afterwards if you
want them to differ); shrinking keeps the first bars. Changing the meter itself keeps any
hits that still fit. For loops longer than 4 bars, use **Fill every** on the main tab —
it stretches playback to up to 16 bars without making the grid unwieldy.

Spoken navigation uses the `accessible_output2` library (speaks through NVDA when it is
running, Windows speech otherwise). It installs with the app's UI dependencies.

## Odd & prog time signatures

In the Pattern Editor, set **Beats per bar** and **Beat unit** to anything you like — 5/4,
7/8, 9/8, 6/8, 5/8, and so on. The Step dropdown resizes to fit the meter, and steps stay
named by beat so you always know where you are.

Because the whole loop is one repeating unit, an **odd-length loop naturally cycles against
your playing** — the "lands outside the bar" feel of bands like Meshuggah or Tool. For a
tight djent-style polymeter, try a short loop like **7/16** (Beat unit 16, 7 beats) over a
straight 4/4 pulse. Built-in odd grooves to start from: **5/4, 7/8 (2+2+3), 6/8, 5/8 (3+2),
and Djent 7/16 (poly)**.

Tip: on the **Metronome** tab, check **Non-standard meter** to reveal the beat unit and a
matching **Accent grouping** field (e.g. `2+2+3` for a 7) so its click accents the groups
the same way. Leave it unchecked for a shorter, simpler tab in everyday 4/4 use.

## Choosing each part's sample (Kit Sounds…)

A part folder often holds dozens of samples, and producer kits mix true drum hits with
**vocal chops** ("AHH", "HEY"), bells, and sound effects. The **Kit Sounds…** dialog lets
you pick each part's sample by ear:

1. Pick a **Part** (Kick, Snare, Perc, …).
2. Arrow through its **Samples** — **each one plays as you land on it**, with its length
   shown. **Preview** replays the current one.
3. **Save** remembers your choices for that kit (they persist across restarts and
   reloads); **Cancel** or Escape leaves everything as it was.

When you haven't chosen, the app picks a sensible default: for drum parts it skips
vocal-named files (AHH, HEY, OOH, …) and anything too long to be a hit, taking the first
short, drum-like sample instead. 808 and FX parts are allowed to ring.

## Bringing your own kit

A kit is a **folder** whose subfolders are named for drum parts, each holding one or more
`.wav` files. The looper picks one sample per part (see Kit Sounds above for how, and how
to override it).

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
