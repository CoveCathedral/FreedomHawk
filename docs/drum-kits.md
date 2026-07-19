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
| **Build Kit…** | Make a **new kit from scratch**, part by part, by ear — see below. It lands in the Kit list next to Import. |
| **Import Drum Kit…** | A separate button that opens the folder picker to load a kit from anywhere. The app remembers where your kits live. |
| **Category** | Filters the Groove list by genre family (Rock, Funk, Trap, 5/4…) — plus any categories you create when saving your own patterns. |
| **Groove** | 500 built-in patterns across ~60 genres — rock, punk, metal, funk, disco, hip-hop, trap, drill, house, techno, drum & bass, dubstep, reggae, ska, bossa, samba, afrobeat, jazz swing, blues shuffle, waltz, gospel 6/8, odd meters (5/4, 7/8, 9/8, 11/8…), and more — each a base groove plus numbered variations (names ending in "fill" include a drum fill), followed by **your saved patterns** shown with their category. First-letter navigation works in the list. |
| **Fill every** | For jamming: stretches the groove so the fill only comes around every 2, 4, 8, 12, or 16 bars — plain groove until then, fill as the turnaround, crash on the restart. "Pattern length" plays the groove exactly as written. |
| **Fill style** | "As written" plays the groove's own fill. **"Improvised"** generates fresh fills on every render — varying length (short, long, occasionally a whole bar) and density, Diablo-style rule-bound randomness — so the groove rarely repeats itself exactly. Fills follow the **Fill every** cadence (a 4-bar cycle when it's unset) and always land on the meter, odd time signatures included. |
| **Tempo** | 30–300 BPM. (A screen reader announces the real BPM, not a percentage.) |
| **Drum volume** | Master volume for the drums (0–100%), so they sit right against your guitar. |
| **Part** + **Mute this part** | Pick a part and mute/unmute it live, without touching its steps. |
| **Edit Pattern…** | Opens the Pattern Editor dialog. |
| **Kit Sounds…** | Choose which sample each part uses (sample kits only — the synth kit's sounds are fixed). See below. |
| **Count-in** | When checked, **Start** first plays one bar of clicks (accented downbeat, at your tempo and meter) so you can come in on time; the loop then begins. Stop during the count-in cancels it. |
| **Tempo trainer** + **Trainer Options…** | When checked, the loop **speeds up as you play** to build your chops. See below. |
| **Start / Stop** | Begins/ends the loop. Changes while playing take effect on the next loop. **F5** does the same from anywhere in the window, so you needn't tab to this button — it speaks the new state. |

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
| **Number keys** (`1`–`9`, `0`) | Set the cursor hit's **play chance**: 1–9 is 10–90%, 0 makes it always play. A "sometimes" hit **rolls fresh on every pass**, so the groove varies itself — see below. Spoken ("Hi-hat 50 percent chance, Beat 2.3"). |
| **F** | Cycle the cursor hit's **ornament**: plain → **flam** (one soft grace stroke just before) → **drag** (two — a ruff) → **roll** (the stroke rebounds across its step, a ratchet) → plain. Spoken ("Snare flam, Beat 2"). See below. |
| **Ctrl+Z / Ctrl+Y** | **Undo / redo** any edit — steps, dynamics, chances, ornaments, tuning, volume, choke, line length, meter changes, adding/removing lines, sample picks, even a whole Load Groove — up to 100 steps, from anywhere in the editor. Spoken with what changed ("Undone: meter change"). |
| **R** | **Read this line's rhythm** as beat positions ("Kick, 2 hits: Beat 1; Beat 3") — learn a groove without arrowing across every step. Dense lines cap at 24 positions ("and N more"). |
| **S** | **Audition the cursor step**: names and plays everything landing there across all lines ("Beat 2.2: Kick, Hi-hat ghost") — one vertical slice of the groove. An empty step says "nothing". |
| **Alt+P** | Play / pause the audition **without leaving the grid** — focus stays on the step you're editing. |
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

**What to expect from real packs.** The **808s and basses** — the sounds you actually tune
to a key — read cleanly and confidently; a bank of 808s tuned to C will all speak around
**C1/C2**, so matching your song's key is straightforward. **Kicks and toms** get a key too,
and usually land on the note or within a semitone of it (where a pack writes the note into
the file name, like `..._G#`, the readout tends to agree) — but a drum's "pitch" is
genuinely fuzzy, so treat a kick/tom key as a strong hint, not gospel, and trust your ear
with `P`. A few click-heavy sounds will say **no key** instead of guessing; that's the
confidence gate working, not a failure. Nothing needs tagging — just drop the kit in and
arrow through it.

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

### Chance steps ("sometimes" hits)

Give any hit a **play chance** with the number keys: cursor on the hit, press **5** and it
becomes a 50% hit — sometimes it plays, sometimes it sits out, **re-rolled on every pass**
so the loop never sounds stamped out. `1`–`9` set 10–90%, **0** returns it to always.
It's how real drummers work: the backbone (kick, snare backbeat) solid, the decoration
(extra hat taps, ghost snares, a perc flourish) coming and going.

- The state is spoken everywhere the cursor reads ("hit, 30 percent chance"), the line's
  row counts its chance steps ("8 hits (2 by chance)"), and the visual track draws them
  half-filled — literally a "maybe".
- A loop with chance steps bakes **four varying passes** into itself, so the variation is
  audible even while a single WAV loops; songs re-roll **every repeat** of a section.
  Fills, feel, dynamics and polymeter all combine with it, and it saves, shares, and
  exports with the pattern (WAV renders roll like playback; MIDI exports the hits as
  written).
- Try it: load any groove, add 2–3 extra hi-hat or perc hits, set them to 30–50%. The
  groove starts breathing.

### Ornaments — flams, drags, rolls

Press **F** on a hit to cycle its ornament — the rudiments drummers decorate strokes with:

- **Flam** — one soft grace stroke a hair before the main hit ("fla-DAM"). Fattens a
  backbeat instantly.
- **Drag** — two quick grace strokes leading in (a ruff): "bl-l-DAM".
- **Roll** — the stroke rebounds across its step (what hardware boxes call a ratchet):
  four rapid decaying strokes. Great on snare builds and hat stutters.

Grace strokes whisper next to the main stroke and follow everything the hit does —
tuning, volume trim, dynamics, swing, humanize, even a play chance (skip the hit, skip
its ornament). The row counts them ("4 hits (1 ornamented)"), the cursor speaks them
("accent, flam"), the visual track marks them with a bright tick on the cell's left
edge, and they save, share, and round-trip with the pattern. Roll spacing follows the
step length, so it stays musical at any tempo and grid. (MIDI export writes the main
hits as written; grace strokes are an audio-render detail.)

### Fills — mark a span, drop a fill

Press **`;`** to set a start marker and **`'`** an end marker (a span across all lines,
spoken as you set them), then **`L`** to carve an **improvised fill** across it — or across
the whole pattern if nothing's marked. It asks a **complexity** (how busy — a sparse
tom-and-snare run up to a dense roll) and **"let the fill spill past the end"** (off by
default, so the fill resolves on the bar with a crash on the next downbeat). Fills roll
down the full kit's toms, Tom 1 to the floor tom; any part the fill introduces (a tom, a
crash) gets its own line automatically, and the whole thing is a single **Ctrl+Z** away.
(This is the same fill you get in the Song Beat Editor, where the span keys are `[` and
`]` since `;`/`'` aren't tuning there.)

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

**Feel — saved with the groove.** Two sliders below the meter controls set this pattern's
own feel, so it travels with the groove (a shuffle keeps its shuffle) and into any song
that uses it:

- **Swing** (0–100%) — delays the off-beats for a shuffle feel; 0% is straight, higher
  approaches a triplet shuffle.
- **Humanize** (0–100%) — adds subtle per-hit timing and volume drift so a looped groove
  doesn't sound stamped out.

They apply to the editor's Play, to main-tab playback of that groove, to WAV export, and
per-section in songs. (They used to live on the main tab; moving them here declutters it
and makes feel part of each groove.)

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
The **Song Builder** has three tabs so it doesn't crowd:

- **Arrange** — the list of **sections** (each a groove + a repeat count) and a
  **high-contrast visual timeline** beneath it: one coloured block per section, its width
  showing its length, the selected one outlined (a low-vision aid; the list stays what you
  operate). In the list: **Up/Down** select, **Left/Right change repeats** (Left takes a
  repeat away — added one too many? one keypress fixes it), **Shift+Left/Right by HALF a
  loop** — extend a verse by just half ("Rock x2.5", spoken "2 and a half repeats"; an
  Improvised-fill section rounds to whole cycles when it plays), **Alt+Up / Alt+Down
  reorder**, **Delete** removes the section, **E** edits it — each spoken, with the
  running song length. Below the list, the selected section has its own controls, all **live while the
  song plays** (it re-renders and restarts, so you can trial a change on the fly):
  - **Edit Section…** — opens the Pattern Editor on that section's groove; your tweaks are
    stored **inline in the song** (they don't touch the original groove or your library), so
    you can pin down a section's exact feel. Edited sections read "(edited)".
  - **Tempo** — "Song tempo" (follow the song) or a per-section BPM, so a song can **build
    speed into the chorus** or drop for a breakdown. Each section renders at its own tempo.
  - **Kit** — "Global kit" (follow) or a specific kit, so a **verse can be on one kit and
    the chorus on another** (e.g. acoustic verse, 808 chorus).
  - **Swing** — "Groove's own" (the feel saved with the groove) or a 0–100% override for
    just this section: a straight verse, a swung chorus, no editor round-trip needed. 0%
    is a real override (force straight).
  - **Fills** + **Fill amount** — "As written", or **Improvised**: every repeat of the
    section becomes a cycle **ending in a freshly generated fill** (crash on the next
    downbeat), so a 4-repeat verse gets four different turnarounds. Fill amount makes
    them longer and busier.

  **Bulk edit — mark several sections with M.** Press **M** on a section to mark it (spoken,
  with the running count; the row reads "marked"). To put sections 3 and 4 — but not the
  others — at 140 BPM: mark both, then **with the cursor on one of them** set Tempo once,
  instead of tab-down-set, tab-down-set. The change reaches **every marked section** (mark
  any combination — 3 and 4, or 5 and 9). The edit always includes the section you're on,
  so if the cursor is on an **unmarked** section the controls change just that one and any
  marks elsewhere are ignored — a stray leftover mark can never quietly redirect an edit
  to a section you can't see. Repeats, reorder, Delete and Edit always act on the section
  under the cursor, never the whole marked set — no accidental bulk deletes. Press **M**
  again to unmark.

  **Keyboard, from anywhere in the dialog:** **Alt+1 / Alt+2 / Alt+3** jump straight to
  the Arrange / Add / My Songs tabs (spoken, focus landing on the tab's list), **Alt+P**
  plays or stops the song, and **Alt+V** previews the Add tab's groove — all **without
  moving your focus**, so NVDA stays on the section you're working.
- **Add** — narrow the **Category** dropdown to a genre first (so you're not scrolling all
  500), choose the **Groove**, set **Repeats** (plus starting **Swing** and **Fills** for
  the new section, editable later on Arrange), pick **Insert at** — **End of song** (the
  default) or **before any existing section** ("Before 1" is the very start) — then press
  **Add Section**. Where it landed is spoken ("Added Funk at position 2 of 5"), and the
  position resets to End of song after each add so a stale choice never surprises you.
  **Preview Groove** (or **Alt+V**) loops the selected groove (on the current kit and
  tempo) so you can **hear it before you add it**; press it again — or Add Section — to
  stop. (Sections reference grooves by name — built-in or your saved patterns — so **save
  your own pattern as a preset first** to use it in a song.)
- **My Songs** — a list of your saved arrangements: select one and **Load** it into Arrange,
  **Play** it, or **Delete** it. **Save Current Song** stores what you've built, and **Export
  as WAV** writes the whole thing as one audio file.

**Polymeter stays inside its section.** A line with its own odd length (the per-line
polymeter from the Pattern Editor) keeps cycling through the whole section — the phrasing
carries across the section's repeats — and is **cut off cleanly at the section's end**, so
the next section always starts on its own count. Odd meters stay expressive without
wrecking the math downstream. Prefer the old loose behavior? Check **"Polymeter lines
push past section ends"** on the Arrange tab (each repeat then runs the full realignment
loop until every line comes back around); the choice saves with the song. This governs
sections that play **as written**; a section set to **Improvised** fills is rebuilt cycle
by cycle, so it already fits its own length regardless of the toggle.

**Unsaved work is guarded.** Closing the Song Builder with an unsaved arrangement asks
**Save / Don't save / Cancel** (an empty builder just closes), and **Load**/**Play** over
unsaved work asks before replacing it — time spent arranging never vanishes on an
accidental Escape.

### The Song Beat Editor (Beat Editor… — fine control across the whole song)

The **Beat Editor** button opens the same spoken tracker grid you know from the Pattern
Editor, but stretched across the **entire song** — every section, every repeat — so you can
get in and place hits beat by beat wherever you are in the arrangement.

Because the surface is much bigger, the cursor moves by **musical unit**:

| Key | Moves |
|-----|-------|
| **Left / Right** | one step |
| **Shift + Left / Right** | one beat |
| **Ctrl + Left / Right** | one bar |
| **Ctrl+Shift + Left / Right**, or **Page Up / Down** | one section |
| **Home / End** | the start / end of the whole song |
| **Up / Down** | choose a part |

Every move is spoken with where you are — e.g. *"Section 2, Chorus, repeat 2, bar 1, beat
3. Snare: hit"* (the section number leads, so two same-named sections are never confused).
**Space** cycles the hit under the cursor (on → accent → ghost → off) and **F** cycles its
ornament (flam → drag → roll), exactly as in the Pattern Editor. **F1** lists the keys.

- **Markers and fills** — press **`[`** to set a start marker and **`]`** an end marker
  (a span across all parts, spoken as you set them). **`L`** drops an **improvised fill**
  across that span — or across the whole section if nothing's marked. It asks two things:
  a **complexity** slider (how busy — a sparse tom-and-snare run up to a dense roll) and
  **"let the fill spill past the end"** (off by default, so the fill **resolves on the
  bar** with a crash on the next downbeat; on, it stays busy right through). Fills use the
  full kit's toms, descending from Tom 1 to the floor tom as the run goes.
- **`T`** opens a tempo dialog for the section under the cursor — set a per-section BPM
  (or "Song tempo" to follow the song) without leaving the grid.
- **Hearing it** — three ways to listen: **Play section** (button) loops the section
  you're on, the working audition while you edit; **Play song** plays the whole
  arrangement through once from the top; **Play from here** (or the **`P`** key) plays the
  whole song from the cursor position, so you can drop in right where you're working
  (**Shift+P** plays from the top). Press **`P`** again to stop.
- **Add Line…** brings any part of the full kit into the song (a floor tom, a cowbell, a
  second crash), ready to place across any section.
- **Edit scope** — by default an edit changes the section's pattern **everywhere it
  repeats**. Check **"Edit this repeat only"** to vary a single pass: the repeat you edit
  **splits off into its own section** so your change lands there alone and the other
  repeats keep playing as they were.
- **Play section** auditions the section under the cursor as a loop; **Save** applies your
  edits back to the arrangement (edited sections become their own inline patterns, so the
  shared library grooves are never touched), **Cancel** discards them.

**Play** (always at the bottom) renders the song end to end and **plays it through once, then
ends** — a song has an ending. Sections can even be in different meters (a 4/4 verse into a
7/8 bridge); each is rendered at its own meter and stitched gapless. Song mode is in both
FreedomHawk and standalone Sequin.

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
2. Pick the **From kit** — normally "This kit", but you can source the part from **any
   other kit you have** (see hybrid kits below).
3. Arrow through its **Samples** — **each one plays as you land on it**, with its length
   shown. **Preview** replays the current one.
4. **Save** remembers your choices for that kit (they persist across restarts and
   reloads); **Cancel** or Escape leaves everything as it was.

When you haven't chosen, the app picks a sensible default: for drum parts it skips
vocal-named files (AHH, HEY, OOH, …) and anything too long to be a hit, taking the first
short, drum-like sample instead. 808 and FX parts are allowed to ring.

### Hybrid kits (mixing kits in Kit Sounds)

The **From kit** dropdown lists every kit that has the selected part, so a kit can borrow
parts from its neighbours: keep this kit's kick, take the snare from your cassette kit and
the hats from an 808 pack. Two things worth knowing:

- **Gaps get filled.** The Part list includes parts this kit never shipped — a kit with no
  808 folder can still get an 808, sourced from any kit that has one. Only kits that
  actually have the part are offered, so there are no empty dead ends.
- **It saves with this kit.** The borrowed picks are stored as part of this kit's Kit
  Sounds choices, so the hybrid comes back whenever you select the kit — in the main tab,
  in the editor's follow-the-kit lines, and in songs that name it as a section kit. If a
  borrowed kit is later renamed or removed, that part quietly falls back to this kit's own
  default rather than breaking.

## Building a kit from scratch (Build Kit…)

**Build Kit…** (next to the Kit list) makes a **brand-new kit**, part by part, by ear —
where Kit Sounds tweaks an existing kit, this starts from nothing.

1. **Name** the kit.
2. Pick a **Part** (every part of the full kit is available — kick through floor tom,
   cowbell, ride bell, and the rest).
3. Choose the **Sound from** — **Synth** (the built-in voice, the default) or any kit
   you've imported — then arrow the **Sample** list to hear each option. Tuned sounds
   speak their key, so you can match 808s and toms.
4. **Save Kit** writes it and selects it straight away.

The result is a **real, self-contained kit folder** under `Samples/`: the samples you
chose are copied in, and every part you left on **Synth** has the synth voice baked to a
file — so nothing is silent, the kit plays even if you later delete the kits you borrowed
from, and you can refine it afterwards in **Kit Sounds** or share the folder like any other
kit. (Built kits live under the git-ignored `Samples/`, so borrowed third-party sounds
never end up in the public repo.)

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

Folder names are matched **loosely and case-insensitively**, so the names sample packs
actually ship just work — plurals (`Kicks`, `Snares`), spaced and worded names
(`Closed Hats`, `Organic Percussions`, `808 Bass`), and keyword matches (anything with
"perc" in it is percussion, "hat" is a hi-hat, and so on):

| Part | Matches names containing… |
|------|---------------------------|
| Kick | `KICK` |
| Snare | `SNARE`, `RIM`, `RIMSHOT` |
| Hi-hat (closed) | `HIHAT`, `HI-HAT`, `HAT`, `CH`, `CLOSEDHAT` |
| Open hat | `OPENHAT`, `OPEN HAT`, `OH` |
| Clap | `CLAP`, `SNAP` (finger snaps ride with the claps) |
| Rimshot / cross-stick | `RIMSHOT`, `RIM`, `SIDESTICK`, `CROSSSTICK` |
| Hi-hat (pedal) | `PEDALHAT`, `PEDAL`, `PH` |
| Toms | `TOM` → the mid tom; `HIGH TOM`/`RACK TOM` → Tom 1, `FLOOR TOM` → Floor tom |
| Crash 1 / 2 | `CRASH`, `CYMBAL`; `CRASH2` → Crash 2 |
| Splash / China | `SPLASH`, `CHINA` |
| Ride / Ride bell | `RIDE`; `RIDE BELL`/`BELL` → Ride bell |
| Cowbell / Tambourine / Shaker | `COWBELL`, `TAMBOURINE`/`TAMB`, `SHAKER`/`MARACAS` |
| Perc | `PERC`, `CONGA`, `BONGO`, `CLAVE`, `WOODBLOCK`, `TRIANGLE`, `DJEMBE` |
| 808 / sub | `808`, `BASS`, `SUB` |
| FX | `FX`, `TEXTURE`, `IMPACT`, `RISER`, `SWEEP`, `NOISE`, `STAB`, and anything with **`LOOP`** in the name |

**Several folders can feed one part.** If a pack has `Percussions`, `Organic Percussions`
and `Congas`, all three are **merged** into the Perc part — every sample stays pickable in
Kit Sounds. Loops and textures are routed to **FX** (which grooves rarely trigger) so they
don't crowd out the real one-shot drums. Anything the matcher doesn't recognise (a `Readme`
or `Vocals` folder) is simply left out, never misfiled.

### The full standard kit

Every part of a complete drum kit is always available — **kick, snare, rimshot, clap,
closed / pedal / open hats, five toms (Tom 1 high → Floor tom), Crash 1 and 2, splash,
china, ride, ride bell, cowbell, tambourine, shaker, 808 and perc** — with a built-in
synth voice for each, so the whole palette is playable even before you load a sample kit,
and improvised fills always have their parts. A kit you import only needs the parts you
have; any part it's missing falls back to the synth voice, so nothing ever goes silent.
The editor doesn't clutter with all of them: a pattern shows the parts it uses plus the
core (kick, snare, hats), and **Add Line…** reaches the rest of the kit (a floor tom, a
second crash, a cowbell) whenever you want them.

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
