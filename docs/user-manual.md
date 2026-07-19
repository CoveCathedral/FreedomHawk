# FreedomHawk User Manual

Welcome to FreedomHawk — an accessible, screen-reader-first editor for the Line 6
Firehawk FX, with a built-in suite of practice tools. This manual is written for
keyboard and screen-reader use throughout: every feature described here works without a
mouse and announces itself. It is structured with heading levels, so you can navigate it
the same way you navigate the app — by jumping between headings.

A note on what works today: **everything in this manual works right now except live
pedal control**, which is in its final validation stage. Tone editing, presets, the
tuner, the metronome, and the entire drum machine are fully functional offline. See
"The pedal connection" near the end for the current state of live control.

## Getting started

### What you need

- Windows, with Python 3.10 or newer installed.
- If you use a screen reader, FreedomHawk is built and tested with **NVDA**. Spoken
  feedback also works through Windows speech when NVDA isn't running.
- Optionally: your Firehawk FX paired over Bluetooth (for the play-along feature now,
  and live control later).

### Installing

From the project folder, in a terminal:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[ui,dev]"
```

### First run: your tone data

FreedomHawk ships none of Line 6's data. You generate it once, locally, from a copy of
the discontinued Firehawk Remote app (an APK file) that you lawfully have:

```powershell
.venv\Scripts\python tools\extract_assets.py path\to\firehawk-remote.apk
```

This fills in the 261 amp, cab, and effect models the editor works with. It only ever
lives on your machine.

### Launching

Double-click **`Firehawk.bat`**, or run `.venv\Scripts\python -m firehawk`.

**After updating the app's code, restart it** — a running copy keeps using the code it
launched with.

## The main window

The window is a list of tabs down the left side, with each tab's controls to the right.
The tabs are: **Presets**, one tab per signal-chain block (Wah, Compressor, Noise Gate,
Amp, Cabinet, EQ, FX 1–3, Reverb, Volume Pedal, Variax, Global), and the practice tools
(**Tuner**, **Metronome**, and **Sequin** — the accessible drum sequencer).

### Moving around

- **Up/Down arrows** on the tab list move between tabs; **Tab** moves into a tab's
  controls; **Escape** steps back out (controls → tab list → Presets).
- **Ctrl+1 through Ctrl+9** jump straight to the first nine tabs; **Ctrl+B** returns to
  Presets from anywhere.
- **F5** plays or stops the current tab's loop from anywhere in the window — the Sequin
  and Metronome tabs — so you never have to tab to the Start button. It speaks the new
  state ("Drum loop started…", "Metronome stopped"), and a tab with no loop says so.
- **F1** opens the complete keyboard-command list at any time.
- **Alt** opens the menus: File, Go, Settings, Tools, Device, Help.

### Making it yours

- **Settings → Arrange Tabs…** reorders the tabs: select one, press **Alt+Up** or
  **Alt+Down** to move it, OK to apply. The order persists between sessions. The first
  tab is where the app starts, and Ctrl+1–9 follow your order.
- **Settings → Dark Mode** toggles the high-contrast dark theme with large white labels
  (on by default).

## Presets and tone editing

### The Presets tab

A list of every preset — factory and your own — with a details pane that reads the
selected preset's full signal chain. From here you can **Open** a preset into the
editor, **Save Current As…**, **Delete**, and **Refresh**.

### Editing a tone

Each block tab (Amp, Reverb, FX 1, …) has:

- an **enabled checkbox** to switch the block on or off,
- a **model dropdown** to choose which amp/effect the block runs,
- one labelled control per parameter: **sliders** for continuous values (they announce
  real values — decibels, BPM, percent — not raw positions), **dropdowns** for stepped
  choices, **checkboxes** for switches.

Changing the model rebuilds the parameter list for the new model. All names and ranges
come from the pedal's own data — nothing is approximated.

### Saving and files

- **Ctrl+N** — new preset. **Ctrl+S** — save to your library (you'll be asked for a
  name). **Ctrl+O** — open a preset file. **File → Export Preset to File…** writes the
  current tone as a JSON file you can back up or share.
- If you have unsaved changes, the app offers Save / Discard / Cancel before anything
  would overwrite them.
- **Settings → User Presets Folder…** tells you where your library lives on disk.

## The Tuner

Tune by ear against a sustained reference tone — no lights, no meters.

1. Pick your **instrument**: 6, 7, or 8-string guitar, or 4, 5, or 6-string bass.
2. Pick a **tuning** — from standard through drop tunings, open tunings, DADGAD,
   all-fourths, and more.
3. Press a **string button** to hold that string's tone; tune to it; press again (or
   **Stop Tone**) to stop. The tone also stops when you leave the tab.

## The Metronome

- **Tempo**: 30–300 BPM (spoken as real BPM). **Tap Tempo** sets it from your taps.
- **Beats per measure** and **Subdivision** (quarters, eighths, triplets, sixteenths).
- For odd meters, check **Non-standard meter** to reveal the beat unit and an **Accent
  grouping** field: type `2+2+3` for a 7/8 and the click accents each group's start.
  Unchecking returns to standard timing.
- The metronome **keeps running while you work in other tabs** — press Stop or close
  the app to end it.

## Sequin — the drum sequencer

**Sequin** is FreedomHawk's full accessible drum machine and step sequencer. The short
version: pick a kit and a groove, press Start, and jam — then go as deep as you like. The
complete guide, including how to use your own sample libraries, is in `docs/drum-kits.md`;
this is the tour. Sequin also **runs on its own** — double-click **`Sequin.bat`** (or
`python -m firehawk.sequin`) to open a two-tab window with the **sequencer** and a
**metronome**, with its own menu.

### The main tab

- **Kit** — the built-in synth kit (works with no files), plus any drum-kit folders in
  your `Samples` folder. **Import Drum Kit…** loads a kit folder from anywhere.
- **Kit Sounds…** — choose which sample each part uses, by ear: pick a part, arrow
  through its samples (each plays as you land on it), Save. The **From kit** dropdown
  sources a part from **any other kit** — build a hybrid (this kit's kick, another's
  snare), or borrow a part this kit doesn't have (an 808 for a kit that shipped none).
  Hybrids save with the kit and come back whenever you select it.
- **Category** — filter the grooves by genre family, including categories you create.
- **Groove** — 500 built-in patterns spanning ~60 genres (rock, metal, funk, hip-hop,
  trap, house, techno, drum & bass, reggae, latin, jazz, odd meters, and many more) plus
  your saved ones. Names ending in "fill" include a drum fill; **Category** filters by
  genre.
- **Fill every** — stretch the groove so the fill only comes around every 2–16 bars.
- **Fill style** — "As written", or **Improvised**: freshly generated fills every time,
  varying length and density, always on the meter.
- **Tempo** and **Drum volume** sliders (both spoken as real values). (Swing and Humanize
  now live in the Pattern Editor, saved with each groove — see below.)
- **Part** + **Mute this part** — silence any part live without erasing its steps.
- **Count-in** — when checked, Start plays one accented bar of clicks at your tempo and
  meter before the loop, so you can come in on the downbeat. Stop during it cancels.
- **Tempo trainer** + **Trainer Options…** — when checked, the loop starts at the current
  tempo and **speeds up as you play**, announcing each new BPM. In **Trainer Options** set
  how much it climbs (BPM per step), how often (bars per step), the target, and whether to
  **keep climbing past the target** (endurance mode) or stop and hold there (a defined
  ramp). Great for pushing a fill from slow to fast, hands-free.
- **Start/Stop** — the loop keeps playing across tabs, like the metronome.

### The Pattern Editor

Open with **Edit Pattern…**, or press **Ctrl+D anywhere in the app** for a blank one.
It's a tracker-style grid: one line per drum, and a time cursor on the arrow keys with
**every move spoken** ("Bar 2, Beat 3.2, hit"):

- **Up/Down** — move between lines. **Left/Right** — move by step; **Ctrl** by beat;
  **Ctrl+Shift** by bar; **Home/End** — start and end.
- **Space** — cycle the step: **on → accent → ghost → off**, each spoken. Accents hit
  harder and ghosts whisper, so grooves get real dynamics. **Enter** — this line's
  sample options (any sample from its kit, the automatic default, or None to silence
  it). **Delete** — remove a line. **P** — preview the line's sound. **F1** — speak the
  key list.
- **Minus / Plus** (`-` / `+`) — set this line's own **loop length** for polymeter:
  give the kick 7 steps while the hats stay at 16 and the parts phase against each
  other and realign — the stacked-meter prog/djent feel. The pulse stays shared, and
  each line is edited as its own loop.
- **Brackets** (`[` / `]`) — **tune** this line down / up a semitone (Shift for a whole
  octave), so an 808 or tom sits in your key. The resulting **note is spoken** ("Kick
  tuned +2, A1"), `P` speaks the note a line plays, and the row shows its tuning.
  FreedomHawk estimates each sample's key by ear, so you can tune to a target pitch
  without seeing anything; noise sounds (hats, cymbals) simply report no key.
- **Comma / Period** (`,` / `.`) — set this line's **volume** in decibels (Shift for a
  6 dB step), spoken as you go. Balance the parts — pull a boomy or octave-dropped kick
  back so it doesn't wash out the rest. It saves with the pattern; the main tab's **Drum
  volume** still rides the overall level on top.
- **C** — cycle this line's **choke group** (none → 1–4 → none). Lines in the same group
  cut each other's ring, like a closed hat choking an open hat: put both hats in group 1
  and each closed hit silences the open hat's tail. Works for cymbal chokes too. Saved
  with the pattern.
- **Number keys** (`1`–`9`, `0`) — set the cursor hit's **play chance**: 5 makes it a 50%
  "sometimes" hit that **rolls fresh on every pass**, so the loop varies itself like a
  real drummer decorating a groove. 0 returns it to always. Spoken everywhere the cursor
  reads, counted in the row ("8 hits (2 by chance)"), shown half-filled on the visual
  track, and saved with the pattern. Songs re-roll every repeat of a section.
- **F** — cycle the cursor hit's **ornament**: **flam** (a soft grace stroke just
  before), **drag** (two — a ruff), **roll** (the stroke rebounds across its step, a
  ratchet), then back to plain. Spoken, marked on the visual track, saved with the
  pattern; grace strokes follow the hit's tuning, volume, dynamics, feel, and chance.
- **Ctrl+Z / Ctrl+Y** — **undo / redo** any edit (steps, dynamics, chances, ornaments,
  tuning, volume, chokes, line length, meter changes, add/remove line, sample picks,
  Load Groove), up to 100 steps. Spoken with what changed ("Undone: step change").
- **R** — read the current line's **whole rhythm** as beat positions ("Kick, 2 hits:
  Beat 1; Beat 3"). **S** — name and play **everything on the cursor step** across all
  lines ("Beat 2.2: Kick, Hi-hat ghost"); an empty step says "nothing". **Alt+P** —
  play/pause the audition without leaving the grid.
- The **Kit** applies to the whole pattern; lines follow it unless you give one its own
  source. Use **Kit Sounds…** to set which sample a part uses across the whole kit at
  once (e.g. reassign every kick to one sound).
- **Add Line…** — stack drums and mix libraries: any part, following the kit, from synth, or any kit
  you have, up to 24 lines.
- The **time signature** lives here: beats per bar, beat unit, grid resolution, bars
  (1–4). Odd meters welcome — 5/4, 7/8, whatever you play. Growing the bar count
  repeats your music into the new bars.
- **Swing** and **Humanize** sliders (0–100%) set this groove's **feel**, and it **saves
  with the pattern** — a shuffle keeps its shuffle. Swing delays the off-beats toward a
  triplet shuffle; humanize adds subtle per-hit timing and volume drift so the loop isn't
  stamped out. The feel follows the groove everywhere: the editor's Play, main-tab
  playback, WAV export, and per-section in songs.
- **Play/Pause** auditions while you edit; **Save** applies; **Save as Preset…** stores
  the pattern under a category (pick one or type a new one); **Load Groove…** pulls any
  built-in or saved pattern into the editor; **Cancel**/Escape discards.
- **Show visual track** — a checkbox that reveals a large, high-contrast picture of the
  grid for usable vision: one row per line, bright cells for hits, **yellow for accents**,
  **dim blue for ghosts**, gridlines on the beats and bars, and a **red box on the
  cursor** with the current line highlighted. It's display-only — the list above stays the
  thing you operate, so the screen-reader workflow is unchanged — and the setting is
  remembered between sessions.

### Song mode (the Song Builder)

**Tools → Song Builder…** chains grooves into a full arrangement — intro, verse, chorus,
bridge, and so on. It has three tabs:

- **Arrange** — the list of **sections** (each a groove + repeats) with a **high-contrast
  visual timeline** beneath (coloured blocks sized by length, the selected one outlined).
  Up/Down select, **Left/Right change the repeats** (Left removes one — the fix for an
  accidental extra repeat; **Shift steps by half a loop**, so a verse can run x2.5),
  **Alt+Up / Alt+Down reorder**, **Delete** removes, **E** edits
  — each spoken, with the running song length. The selected section has its own **Edit
  Section** (tweak its groove; stored inline in the song), **Tempo** (its own BPM — build
  speed into the chorus), **Kit** (verse on one kit, chorus on another), **Swing** (a
  per-section 0–100% override of the groove's own feel), and **Fills** + **Fill amount**
  (**Improvised** ends every repeat in a freshly generated fill; amount makes them longer
  and busier). All of them apply **live while the song plays**.
  **Bulk edit with M:** press **M** to mark a section (spoken, with the running count).
  To change several at once — say sections 3 and 4 both need 140 BPM — mark them, then
  **with the cursor on one of the marked sections** set the Tempo once; the change hits
  **every marked section**. On an **unmarked** section those controls change just that
  one, and any marks elsewhere are ignored — so a stray mark can never redirect an edit
  to a section you're not on. Repeats, reorder, Delete and Edit always act on the section
  under the cursor. M again unmarks.
- **Add** — filter the **Category** to a genre first (so you're not scrolling all 500), pick
  the **Groove**, set Repeats (plus starting Swing/Fills), press **Add Section**.
  **Insert at** chooses where the new section lands — the end of the song (the default)
  or before any existing section ("Before 1" is the start); what was added and where is
  spoken, and the choice resets to "End of song" after each add. **Preview Groove** (or
  **Alt+V**) loops the picked groove so you can hear it before adding; press it again
  (or Add Section) to stop.
- **Keyboard, from anywhere in the dialog:** **Alt+1/2/3** jump between the tabs (spoken),
  **Alt+P** plays or stops the song, **Alt+V** previews — all without moving your focus.
  (**Alt+P** also plays/pauses inside the Pattern Editor.)
- **My Songs** — a list of your saved arrangements: Load one into Arrange, Play it, or
  Delete it; plus Save Current Song and Export as WAV.
- **Beat Editor** — opens the whole song on one spoken tracker grid for fine, beat-by-beat
  editing across every section. The cursor climbs by musical unit (Left/Right = step,
  Shift = beat, Ctrl = bar, Ctrl+Shift or Page Up/Down = section, Home/End = the song's
  ends, Up/Down = parts), each move spoken as "section, repeat, bar, beat". Space cycles a
  hit, F its ornament, Add Line brings in any kit part, and "Edit this repeat only" varies
  a single repeat (it splits off as its own section). **`[`** and **`]`** mark a span and
  **`L`** drops an improvised fill across it (complexity slider; "spill past the end" off
  by default, so it resolves on the bar); **`T`** sets the section's tempo. See the
  drum-kits guide for the full key list, or press F1 in the editor.

**Play** (at the bottom) renders the whole song end to end (gapless, sections can even be in
different meters) and **plays it through once, then ends**.

**Polymeter at section ends:** by default a line with its own odd length (a 7-step kick
under a 4/4 groove, say) keeps cycling through its section and is **cut off cleanly at the
section's end**, so the next section always starts on its own count — the odd meter stays
inside its section instead of pushing everything after it. Want the old loose behavior for
deliberately weird composing? Check **"Polymeter lines push past section ends"** on the
Arrange tab (each repeat then runs the full realignment loop); the choice is saved with
the song. (This applies to sections playing **as written** — a section set to
**Improvised** fills is regenerated per cycle, so it always fits its own length.)

**Your work is guarded:** closing the Song Builder with an unsaved arrangement asks
whether to save first (Save / Don't save / Cancel), and loading a saved song over unsaved
work asks before replacing it. An empty Song Builder just closes.

Sections reference grooves by name (built-in or your saved patterns), so **save a pattern
as a preset first** if you want your own groove in a song. Song Builder is in both
FreedomHawk and standalone Sequin.

### Managing and sharing (the Tools menu)

- **Drum Pattern Library…** — rename, delete, or recategorize your saved patterns, and
  rename whole categories.
- **Export Drum Loop as WAV…** — the loop exactly as it plays, as an audio file.
- **Export/Import Drum Pattern…** — patterns as small files you can trade with others.
- **Export Pattern as MIDI…** — a standard `.mid` any DAW opens, meter included.
- **Import MIDI File…** — reads a MIDI file's drums and opens them **straight in the
  Pattern Editor**: Play to hear it, tweak, Save to keep it.

## Playing along with music

The Firehawk FX is also a Bluetooth speaker. Pair it with Windows, set it as the
playback device in Windows Sound settings, and any music you play comes through the
pedal while you play guitar over it. No app setting needed — see **Help → Playing Along
with Music** for the steps.

## The pedal connection

Live control — sending your edits to the pedal — is the one feature still in
validation. The protocol has been fully reverse-engineered and implemented; two final
byte-level details await confirmation against a capture of the original app's traffic.
Until then:

- **Device → Connect to Pedal…** finds the pedal's Bluetooth COM port.
- **Device → View Outgoing Messages…** shows the exact bytes each edit would send.
- **Transmit is off by default** and warns before enabling — nothing is written to
  your hardware until the protocol is confirmed safe.

Everything else in this manual is fully usable offline, today.

## Keyboard reference

| Keys | Action |
|------|--------|
| Ctrl+N / Ctrl+O / Ctrl+S | New / open / save preset |
| Ctrl+1 … Ctrl+9 | Jump to the first nine tabs (your order) |
| Ctrl+B | Back to Presets |
| F5 | Play or stop the current tab's loop (Sequin / Metronome), from anywhere |
| Ctrl+D | Blank Drum Pattern Editor, from anywhere |
| Escape | Step back: controls → tab list → Presets; closes dialogs |
| Tab / Shift+Tab | Move between controls |
| Alt | Open the menus |
| F1 | Keyboard-command list (in the Pattern Editor: speaks the grid keys) |
| Alt+Up / Alt+Down | Move a tab (in Settings → Arrange Tabs) |

In the Pattern Editor grid: Up/Down lines · Left/Right step · Ctrl+Left/Right beat ·
Ctrl+Shift+Left/Right bar · Home/End · Space cycle on/accent/ghost/off · minus/plus line length (polymeter) ·
brackets `[`/`]` tune the line (Shift = octave) · comma/period `,`/`.` line volume · C choke group · Enter sample options · Delete remove line · P preview (speaks the note).

## Troubleshooting

- **A button seems to do nothing** — it should never happen (everything speaks); if it
  does, report it. Make sure you restarted the app after an update.
- **No tuner/metronome/drum sound** — check Windows' output device and volume mixer;
  the app plays through the default output device.
- **Spoken grid navigation is silent** — the `accessible_output2` package provides
  direct speech; reinstall dependencies with
  `.venv\Scripts\python -m pip install -e ".[ui]"`.
- **A drum kit loads with missing parts** — the kit folder needs subfolders named
  KICK, SNARE, HIHAT, etc., containing `.wav` files; see `docs/drum-kits.md`. Missing
  parts fall back to the synth kit rather than going silent.
- **The Groove dropdown doesn't show my edited pattern's name** — after editing, your
  working pattern is what plays even though the dropdown still names the last selected
  groove. Save it as a preset to give it a name in the list.

## Getting help and contributing

FreedomHawk is open source (MIT):
[github.com/CoveCathedral/FreedomHawk](https://github.com/CoveCathedral/FreedomHawk).
Issues and pull requests are welcome — screen-reader testing feedback most of all.
