# Firehawk Accessible Controller

An accessible, screen-reader-first Windows application for controlling a Line 6
**Firehawk FX** guitar multi-effects pedal — built because the pedal's only editor was a
discontinued, never-accessible mobile app tied to a dying cloud, leaving a blind owner
unable to reach hundreds of parameters.

The interface is built with **wxPython** (native Windows controls, the same toolkit
NVDA's own interface uses) so every control announces a correct name, value, and range to
NVDA. Every parameter is a labelled slider, spin box, or checkbox; every model a labelled
choice; every block a checkbox you can toggle — all keyboard-navigable.

## Status

- **Working now (offline):** browse the whole signal chain, swap models, edit every
  parameter with correctly labelled controls, and load/save presets as local files.
- **In progress:** live control of the pedal over Bluetooth. The confirmed protocol
  pieces (CRC-16, transport header) are implemented; the remaining on-wire frame format
  is being finalised (see `docs/protocol.md`). No writes are sent to hardware until that
  is validated against a real capture.

See `ROADMAP.md` for the phase plan and `CLAUDE.md` for project conventions.

## Requirements

- Windows, Python 3.10+ (developed on 3.12).
- Dependencies install into a local virtual environment (below).

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[ui,dev]"
```

### First-time: extract the tone data from your own app

FreedomHawk ships **no** Line 6 data. Generate it from an APK of the (discontinued)
Firehawk Remote app that you lawfully have — this keeps the project a clean
interoperability tool that redistributes nothing proprietary:

```powershell
.venv\Scripts\python tools\extract_assets.py path\to\firehawk-remote.apk
```

If the APK is in the project root as `com-line6-firehawk-*.apk`, you can omit the path.
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
  data/        the shipped tone data (models, catalogs, symbol table) extracted from the app
tests/         model, protocol, transport, and UI smoke tests
docs/          protocol.md — reverse-engineering notes
tools/         reverse-engineering helpers (symbol decoder, disassembly, symbol lists)
```

## Provenance

This is interoperability / assistive-technology work on hardware the owner lawfully has,
for a product Line 6 discontinued in 2024. It **redistributes no Line 6 code or data**: the
tone data is extracted locally from each user's own copy of the app (see Setup), and the
notes in `docs/` and `tools/` are working notes toward an independent, clean
reimplementation.
