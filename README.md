# FreedomHawk

**An accessible, screen-reader-first Windows controller for the Line 6 Firehawk FX.**

🦋 *Free the hardware from the dead cloud.*

The Firehawk FX is a guitar multi-effects pedal whose only editor was a mobile app that
was never built to be accessible, was discontinued by Line 6 in 2024, and depends on a
login/cloud layer that is fading. On the pedal itself there are six knobs and a tiny
screen. For a blind or low-vision owner, that left hundreds of parameters — amps, cabs,
effects, reverbs, wah — simply unreachable, and the hardware on a path to becoming a brick.

FreedomHawk is an independent editor that talks to the pedal directly, built so a blind or
low-vision musician can operate the whole device with a screen reader — everything the old
app did, minus the cloud.

## Who it's for

- Firehawk FX owners who use a screen reader (built and tested with **NVDA**).
- Anyone who wants a local, cloud-free editor for the pedal.

## What works today

- **Offline editing (works now):** browse the full signal chain, swap models, and edit
  every parameter with correctly labelled controls; create, load, save, and organise
  presets as local files.
- **Practice tools (work now):** a by-ear **tuner** (sustained reference tones; 6/7/8-string
  guitars and 4/5/6-string basses, full tuning libraries), a **metronome** (odd meters with
  accent grouping, tap tempo), and a full **accessible drum machine** — see below.
- **Live pedal control (in progress):** talking to the pedal over its Bluetooth serial
  link. The confirmed protocol pieces (CRC-16, transport header) are implemented; the
  remaining on-wire frame format is being finalised (`docs/protocol.md`). **Nothing is
  written to the pedal** until that is validated against a real capture.

## Sequin — the accessible drum machine

**Sequin** is FreedomHawk's built-in **accessible step sequencer / drum machine** — a
screen-reader-first, keyboard-only groove sequencer for blind and low-vision musicians
(NVDA-tested). It's **designed non-visually from the ground up** — the spoken tracker grid
*is* the interface, not a visual surface being narrated. That sets it apart from
screen-reader layers added onto sighted DAWs (OSARA over Reaper, and the like), where the
grid is a visual surface a screen reader reads back: here it was built for the ear first,
not retrofitted. Designed hands-on with the blind and low-vision musician it's built for,
Sequin ships inside FreedomHawk and is released **standalone** as its own module too:

- **500 built-in grooves** across ~60 genres (rock, metal, funk, hip-hop, trap, house,
  techno, drum & bass, reggae, latin, jazz, 5/4, 7/8, 9/8, djent polymeters, and more) plus your own
  saved patterns, organised by genre **categories you can create and manage**.
- A **tracker-style Pattern Editor** (Ctrl+D from anywhere): one line per drum, a time
  cursor on the arrow keys (step / beat / bar granularity), every move **spoken directly
  through the screen reader**. Space toggles hits, Enter picks a line's sample, P
  previews — and lines can **stack drums and mix samples from different libraries**.
- **Feel and expression:** per-hit **dynamics** (accents/ghosts), **swing**, **humanize**,
  and true **polymeter** (each line its own loop length, phasing and realigning). Per line:
  **tuning** (with by-ear **pitch detection** that speaks a sample's musical key, so you can
  tune an 808 to your song), **volume** trim, and **choke groups** (a closed hat cuts the
  open hat, as on a real kit).
- **Practice aids:** a **count-in** before the loop, and a **tempo trainer** that speeds the
  BPM up as you play — each new tempo spoken, ramp or endurance mode.
- **Improvised drum fills** — rule-bound randomness that generates fresh fills every
  render, always on the meter, with fill cadences up to 16 bars for jamming.
- **Bring your own drum kits** as plain WAV folders; audition and choose every part's
  sample by ear (no third-party audio ships with the app).
- **Low-vision visual track:** an optional high-contrast picture of the grid in the editor —
  display-only, so the screen-reader workflow is unchanged.
- **Share everything:** export loops as WAV, trade patterns as small JSON files, and
  export/import **MIDI** (General MIDI drum mapping, odd meters preserved).

See [docs/drum-kits.md](docs/drum-kits.md) for the full guide.

## Accessibility

The interface uses **wxPython** — native Windows controls, the same toolkit NVDA's own
interface uses — so every control announces a correct name, value, and range. Only three
control types are used, each one confirmed to read well with a screen reader:

- a **checkbox** for each on/off toggle,
- a **slider** for each continuous value (announces its value as you move it),
- a **dropdown** for each model choice and stepped/enumerated value.

Where a task outgrows standard widgets — the drum machine's pattern grid — the app
**speaks through the screen reader directly** (NVDA when running, Windows speech
otherwise), the same technique accessible DAW tools use, so even tracker-style editing
is fully non-visual.

Everything is keyboard-navigable. Highlights:

- **Escape** steps back (a page's controls → the block list → Presets).
- **Ctrl+1…Ctrl+9** jump straight to a section; **Ctrl+B** returns to Presets.
- **Ctrl+N / Ctrl+O / Ctrl+S** — new / open / save a preset; **Ctrl+D** — drum editor.
- **F1** opens the full keyboard-command list.
- Tabs are **reorderable** (Settings → Arrange Tabs) and the order persists.
- A high-contrast **dark mode with large white labels** is on by default (toggle in
  Settings).

**For low vision** (additive — never at the expense of the screen-reader path): the tab
sidebar is enlarged and high-contrast, the user manual opens as a **navigable HTML page**
(Help → User Manual: table of contents, heading navigation), and the drum editor has an
optional **high-contrast visual track** that mirrors the grid.

## Requirements

- Windows, Python 3.10+ (developed on 3.12).

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[ui,dev]"
```

### First run: bring your own tone data

FreedomHawk ships **no** Line 6 data. You generate it once from an APK of the
(discontinued) Firehawk Remote app that you lawfully have — this keeps the project a clean
interoperability tool that redistributes nothing proprietary:

```powershell
.venv\Scripts\python tools\extract_assets.py path\to\firehawk-remote.apk
```

If the APK sits in the project root as `com-line6-firehawk-*.apk`, you can omit the path.
See `src/firehawk/data/README.md` for details.

## Run

Double-click **`Firehawk.bat`**, or from a terminal:

```powershell
.venv\Scripts\python -m firehawk
```

## Test

```powershell
.venv\Scripts\python -m pytest
```

## Project layout

```
src/firehawk/
  model/       tone model: models, parameters, ranges, symbols, preset/edit-buffer state
  protocol/    the reverse-engineered wire protocol: frames, CRC, message encoders
  device/      the gated bridge from UI edits to protocol messages (transmit off by default)
  transport/   raw byte I/O: Bluetooth SPP COM port, plus an offline simulator
  practice/    the musician tools engine: tuner math, metronome, drum machine, MIDI,
               pattern store — deliberately UI-free (future standalone sequencer project)
  ui/          the accessible wxPython interface, incl. direct screen-reader speech
  data/        tone data — generated locally by tools/extract_assets.py, not in the repo
tests/         model, protocol, device, practice, and UI smoke tests (headless)
docs/          user-manual.md (+ generated .html), drum-kits.md, protocol.md, and more
scripts/       build_manual.py — regenerates the navigable HTML user manual from Markdown
tools/         extract_assets.py, plus reverse-engineering helpers (symbol decoder, etc.)
Samples/       your own drum kits live here (git-ignored; nothing is redistributed)
```

## Why this is legitimate

This is interoperability and assistive-technology work on hardware the owner lawfully has,
for a product Line 6 discontinued in 2024. There is no exploit, no malware, no
copy-protection circumvention, and no third-party target. It **redistributes no Line 6 code
or data** — the tone data is extracted locally from each user's own copy of the app, and
the notes in `docs/` and `tools/` are working notes toward an independent, clean
reimplementation. US law makes explicit room for both purposes (the DMCA §1201 exemptions
for assistive technology and for interoperability, and the long interoperability line of
precedent).

## Documentation

- **[User manual](docs/user-manual.md)** — the full guide, structured for screen-reader
  navigation (also in-app: Help → User Manual).
- **[Drum machine guide](docs/drum-kits.md)** — grooves, the pattern editor, your own
  kits, sharing and MIDI.
- **[Feature coverage](docs/feature-coverage.md)** — everything vs. the original app.
- **[Protocol notes](docs/protocol.md)** and the **[capture guide](docs/capture-guide.md)**
  — the reverse-engineering record and how live control gets validated.

## Contributing

Issues and pull requests are welcome — especially screen-reader testing feedback and help
finalising the on-wire protocol. See `ROADMAP.md` for what's planned and `CLAUDE.md` for
conventions.

## License

MIT — see [LICENSE](LICENSE).
