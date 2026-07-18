# Sequin — the accessible drum sequencer

**Sequin** is FreedomHawk's customizable, screen-reader-first drum machine and step
sequencer. It works out of the box with a **built-in synth kit** (no files needed), and you
can load **your own drum libraries** for higher-fidelity sounds. (Sequin also ships as a
standalone module, so this guide applies whether you reach it through FreedomHawk or on its
own.)

## Quick start

1. Open the **Sequin** tab.
2. Leave **Kit** on "Synth (built-in)", pick a **Groove** (500 built in across ~60 genres —
   basics plus generated variations, many with drum fills), set the **Tempo**, press **Start**.
3. To customize a groove, press **Edit Pattern…** — see the Pattern Editor below.
4. Use **Part** + **Mute this part** to silence a part live without erasing its steps.

The loop keeps playing while you switch to other tabs, so you can jam over it while editing
a tone. Press **Stop** (or close the app) to end it.

## The main tab

| Control | What it does |
|---------|--------------|
| **Kit** | The sound set for the **whole pattern**: "Synth (built-in)" plus any kit folder found in `Samples/`. It applies globally — every part follows it, including any groove or saved pattern you load — unless you deliberately give a line its own source in the editor. Arrowing this list only switches kits; it never opens a dialog. |
| **Import Drum Kit…** | A separate button that opens the folder picker to load a kit from anywhere. The app remembers where your kits live. |
| **Category** | Filters the Groove list by genre family (Rock, Funk, Trap, 5/4…) — plus any categories you create when saving your own patterns. |
| **Groove** | 500 built-in patterns across ~60 genres — rock, punk, metal, funk, disco, hip-hop, trap, drill, house, techno, drum & bass, dubstep, reggae, ska, bossa, samba, afrobeat, jazz swing, blues shuffle, waltz, gospel 6/8, odd meters (5/4, 7/8, 9/8, 11/8…), and more — each a base groove plus numbered variations (names ending in "fill" include a drum fill), followed by **your saved patterns** shown with their category. First-letter navigation works in the list. |
| **Fill every** | For jamming: stretches the groove so the fill only comes around every 2, 4, 8, 12, or 16 bars — plain groove until then, fill as the turnaround, crash on the restart. "Pattern length" plays the groove exactly as written. |
| **Fill style** | "As written" plays the groove's own fill. **"Improvised"** generates fresh fills on every render — varying length (short, long, occasionally a whole bar) and density, Diablo-style rule-bound randomness — so the groove rarely repeats itself exactly. Fills follow the **Fill every** cadence (a 4-bar cycle when it's unset) and always land on the meter, odd time signatures included. |
| **Tempo** | 30–300 BPM. (A screen reader announces the real BPM, not a percentage.) |
| **Drum volume** | Master volume for the drums (0–100%), so they sit right against your guitar. |
| **Swing** | Delays the off-beats for a shuffle feel — 0% is straight, higher approaches a triplet shuffle. |
| **Humanize** | Adds subtle per-hit timing and volume drift so a looped groove doesn't sound stamped out. Applies live, in the editor's Play, and in WAV export. |
| **Part** + **Mute this part** | Pick a part and mute/unmute it live, without touching its steps. |
| **Edit Pattern…** | Opens the Pattern Editor dialog. |
| **Kit Sounds…** | Choose which sample each part uses (sample kits only — the synth kit's sounds are fixed). See below. |
| **Count-in** | When checked, **Start** first plays one bar of clicks (accented downbeat, at your tempo and meter) so you can come in on time; the loop then begins. Stop during the count-in cancels it. |
| **Tempo trainer** + **Trainer Options…** | When checked, the loop **speeds up as you play** to build your chops. See below. |
| **Start / Stop** | Begins/ends the loop. Changes while playing take effect on the next loop. |

### Tempo trainer (build speed)

Check **Tempo trainer** and press **Start**: the loop begins at the current **Tempo** and
**climbs as you play**, so you can push a fill or groove faster over a practice session.
Each tempo change is **spoken** ("115 BPM"), so you hear the climb without watching.

**Trainer Options…** sets how it climbs:

- **Speed up by** — how many BPM to add at each step (1–30).
- **Every** — how many bars to hold each tempo before stepping up (1, 2, 4, or 8).
- **Up to target** — the tempo to climb toward.
- **Keep climbing past the target (endurance mode)** — off = a *defined ramp* that stops
  and holds at the target ("Reached target, holding at 130 BPM"); on = a *continuous* climb
  that keeps nudging up until you Stop (or hit 300 BPM). This is the "both modes" toggle.

It works with **Count-in** (the count leads in, then the climb starts) and with any meter.
Stop ends it at once.

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
| **Minus / Plus** (`-` / `+`) | Set this line's **loop length** — polymeter (see below). |
| **Left / Right bracket** (`[` / `]`) | **Tune** this line down / up a semitone; hold **Shift** for a whole octave. Spoken with the resulting note ("Kick tuned +2, A1"). See below. |
| **Comma / Period** (`,` / `.`) | **Volume** for this line, down / up in decibels (Shift for a 6 dB step). Balance the mix — pull a boomy kick back so it doesn't wash the others out. Spoken ("Kick volume −6 dB"). |
| **C** | Cycle this line's **choke group** (none → 1 → … → none). Lines in the same group cut each other's ring — see below. |
| **P** | Preview this line's sound — and hear its musical key spoken when it has one. |
| **F1** | Speak this key list. |

### Tuning drums & reading their key

Drums that carry a pitch — 808s, kicks, toms, tuned percussion — can be **tuned per
line** with the `[` and `]` keys (Shift for octaves), so an 808 line sits in the key of
your song. Tuning is baked into the sound and travels with the pattern when you save,
share, or export it.

To make that usable without seeing a screen, FreedomHawk **estimates each sample's
musical note** and speaks it:

- **In the Pattern Editor**, `P` previews a line and speaks the note it now sounds
  ("808, G1"). The line's row also reads its tuning ("tuned +2 to A1"), and every `[` / `]`
  press speaks the new note. The note reflects the tuning, so you can dial a line to a
  target pitch by ear and confirmation.
- **In Kit Sounds**, as you arrow through a part's samples, a tuned sample speaks its key
  right after its name — so you can pick the 808 or tom that matches your key.

Noise-based sounds (snares, hats, cymbals) have no clear pitch, so they simply stay
silent on the key readout rather than guess. Detection is automatic and needs no tags —
it listens to the sample the way a tuner would, past the attack, to the note that rings.

### Per-line volume (mixing)

Each line has its own **volume trim** on the `,` and `.` keys (Shift for a 6 dB step),
spoken in decibels. It's the companion to tuning: drop a kick down an octave and it can
suddenly boom over everything, so pull its line back a few dB to sit it back in the mix.
The trim is baked into the sound and saved with the pattern. Full silence isn't the bottom
of this range — for that, set the line's sample to **None** (Enter). The main tab's **Drum
volume** still sets the overall level; per-line trims balance the parts underneath it.

### Choke groups (hi-hat behaviour)

On a real kit an open hi-hat stops the instant you clamp the pedal — the closed hat cuts
it off. Recreate that with **choke groups**: press **C** on a line to put it in a group
(1–4, cycling back to none). **Any lines sharing a group number cut each other's ring** —
so put your **open hat and closed hat in the same group**, and each closed-hat hit chokes
the open hat that's still ringing. The readout names the members ("Open Hat choke group 1,
choking with Closed Hat"). It also works for cymbal chokes, or any "this sound kills that
one" pair. The cut lands exactly on the next hit in the group (with a tiny fade so it
doesn't click), and the setting saves and shares with the pattern.

**Built-in grooves that play both an open and a closed hat come pre-choked** (both hats in
group 1), so open hats close naturally like on a real kit. Press **C** on either hat line
to change or clear it.

### Visual track (low-vision grid view)

Tick **Show visual track** for a large, high-contrast picture of the pattern beneath the
list: one row per line, with **bright cyan cells for hits, yellow for accents, dim blue for
ghosts**, thin gridlines on each beat and bolder ones on each bar, the **current line
highlighted**, and a **red box around the cursor**. It mirrors the grid live as you edit.

It's **display-only and never takes keyboard focus** — the list is still the surface you
operate, so nothing about the screen-reader workflow changes; the picture is an extra for
usable vision (and for anyone who leans on sight more than the primary user does). The
checkbox state is remembered between sessions.

### Polymeter (per-line loop lengths)

Every line normally loops with the whole pattern. But you can give a line **its own
length** with **Minus** (shorter) and **Plus** (longer): set the kick to 7 steps while the
hats stay at 16 and they phase against each other, realigning after a while — the
"time + time + time" stacked-meter feel of prog and djent (Meshuggah, Tool, Soen).

- The pulse is shared — only the cycle *lengths* differ (true polymeter, not different
  tempos), so it stays locked and playable.
- Each line is edited as its **own loop**: the cursor moves within the current line's
  length, and the row announces it ("Kick: 3 hits, length 7 steps, …").
- Playback tiles every line over the least common multiple of all the lengths so they
  resolve; very odd combinations are capped to a sane loop length.
- Saved patterns, WAV, and MIDI export the fully phased loop. (Changing the time
  signature resets per-line lengths, since they're relative to the grid.)

Buttons (all a Tab away):

- **Add Line…** — add another line: pick the part (Kick, Snare, …) and a source —
  **"Follow the selected kit"** (the default: it plays through whatever the main Kit
  dropdown is), the synth, or **any kit library you have** with a specific sample. Give
  lines different sources to stack drums and mix libraries; leave them following the kit
  and they all change together when you switch kits. **Enter** on a line re-picks its
  source/sample the same way.
- **Load Groove…** — replace the editor contents with any built-in or saved pattern.
- **Save as Preset…** — name the pattern, put it in a category (existing or a **new one
  you type**), and it appears in the main tab's Groove list permanently.
- **Play/Pause** auditions the pattern you're editing — with its **feel** (swing and
  humanize) so it sounds musical, but at its own length. The **Fill every** / **Improvised**
  arrangement (which spans many bars) plays on the main tab, not here, so the editor loop
  stays short and easy to work in. **Save** keeps everything; **Cancel** or Escape discards.

**Ctrl+D** anywhere in the app opens a fresh, empty editor on the Sequin tab —
build a pattern from scratch mid-session, save it as a preset, jam on.

## Song mode (Tools → Song Builder…)

Chain grooves into a full arrangement — intro, verse, chorus, bridge, breakdown, outro.
The **Song Builder** is an accessible list of **sections**, each one a groove plus a repeat
count:

- **Add a groove**: choose it from the Groove dropdown, set **Repeats**, press **Add
  Section**. (Sections reference grooves by name — built-in or your saved patterns — so
  **save your own pattern as a preset first** to use it in a song.)
- **In the section list**: Up/Down select a section; **Left/Right change its repeats**;
  **Alt+Up / Alt+Down reorder**; **Delete** removes. Every change is spoken, along with the
  running song length.
- **Play** renders the whole song end to end and loops it. Sections can even be in different
  meters (a 4/4 verse into a 7/8 bridge) — each is rendered at its own meter and stitched
  gapless. **Save Song / Load Song / Delete Song** keep your arrangements; **Export WAV**
  writes the entire song as one audio file.

Song mode is in both FreedomHawk and standalone Sequin.

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
each beat divides), and **Bars in loop** (1–4). **The meter is Beats per bar + Beat unit —
the Grid is only a subdivision, not the time signature.** Changing the Grid from, say,
sixteenths to triplets leaves a 7/8 pattern in 7/8; it just re-spaces the hits on a finer or
coarser lattice. So if your groove reads **4/4**, that is genuinely its meter — to make it
odd, change **Beats per bar** and **Beat unit** (e.g. 7 and 8), not the Grid. After **any**
change here the app speaks the whole resulting state — "**7/8, sixteenth grid, 2 bars**" — so
the meter is always reaffirmed and never silently assumed.

Changing these is **non-destructive**: **growing the bar count repeats the existing music**
across the new bars (shrinking keeps the first bars, and 1→N→1 restores exactly), while
**changing the grid or beats re-quantizes every hit to its musical position** — a backbeat
stays a backbeat, nothing drops out or drifts out of time. (Grids like triplets and
sixteenths don't divide evenly, so flipping between them isn't bit-perfect, but the feel is
preserved; per-line polymeter lengths reset on a grid change.) For loops longer than 4 bars,
use **Fill every** on the main tab.

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
**vocal chops** ("AHH", "HEY"), bells, and sound effects. **Kit Sounds… is the bulk way
to pick sounds**: it sets which sample a part uses **for the whole kit at once** — so
"reassign every kick to this sound" is just choosing the Kick's sample here, not editing
each drum line. Every part follows this globally.

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
