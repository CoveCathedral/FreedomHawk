# FreedomHawk

**An accessible, screen-reader-first Windows controller for the Line 6 Firehawk FX.**

🦋 *Free the hardware from the dead cloud.*

The Firehawk FX is a guitar multi-effects pedal whose only editor was a mobile app that
was never built to be accessible, was discontinued by Line 6 in 2024, and depends on a
login/cloud layer that is fading. On the pedal itself there are six knobs and a tiny
screen. For a blind owner, that left hundreds of parameters — amps, cabs, effects,
reverbs, wah — simply unreachable, and the hardware on a path to becoming a brick.

FreedomHawk is an independent editor that talks to the pedal directly, built so a blind
musician can operate the whole device with a screen reader — everything the old app did,
minus the cloud.

## Who it's for

- Firehawk FX owners who use a screen reader (built and tested with **NVDA**).
- Anyone who wants a local, cloud-free editor for the pedal.

## What works today

- **Offline editing (works now):** browse the full signal chain, swap models, and edit
  every parameter with correctly labelled controls; create, load, save, and organise
  presets as local files.
- **Live pedal control (in progress):** talking to the pedal over its Bluetooth serial
  link. The confirmed protocol pieces (CRC-16, transport header) are implemented; the
  remaining on-wire frame format is being finalised (`docs/protocol.md`). **Nothing is
  written to the pedal** until that is validated against a real capture.

## Accessibility

The interface uses **wxPython** — native Windows controls, the same toolkit NVDA's own
interface uses — so every control announces a correct name, value, and range. Only three
control types are used, each one confirmed to read well with a screen reader:

- a **checkbox** for each on/off toggle,
- a **slider** for each continuous value (announces its value as you move it),
- a **dropdown** for each model choice and stepped/enumerated value.

Everything is keyboard-navigable. Highlights:

- **Escape** steps back (a page's controls → the block list → Presets).
- **Ctrl+1…Ctrl+9** jump straight to a section; **Ctrl+B** returns to Presets.
- **Ctrl+N / Ctrl+O / Ctrl+S** — new / open / save a preset.
- **F1** opens the full keyboard-command list.
- A high-contrast **dark mode with large white labels** is on by default (toggle in
  Settings).

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
  protocol/    CRC-16 + transport header (confirmed); frame + value encoding (in progress)
  transport/   raw byte I/O: Bluetooth SPP COM port, plus an offline simulator
  ui/          the accessible wxPython interface
  data/        tone data — generated locally by tools/extract_assets.py, not in the repo
tests/         model, protocol, transport, and UI smoke tests
docs/          protocol.md — reverse-engineering notes
tools/         extract_assets.py, plus reverse-engineering helpers (symbol decoder, etc.)
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

## Contributing

Issues and pull requests are welcome — especially screen-reader testing feedback and help
finalising the on-wire protocol. See `ROADMAP.md` for what's planned and `CLAUDE.md` for
conventions.

## License

MIT — see [LICENSE](LICENSE).
