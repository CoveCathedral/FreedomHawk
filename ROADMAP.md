# Firehawk Accessible Controller — Roadmap

This file tracks the build in phases. It is plain Markdown with heading levels so it
navigates cleanly in NVDA (press H / heading keys to jump between sections).

## Success benchmark

A solid, fully accessible Windows program that lets a blind user operate the whole
Firehawk FX pedal with NVDA — every feature the old Firehawk Remote app had, **except**
the cloud-dependent tone-cloud browsing. That includes: browsing and recalling the
pedal's presets, editing every parameter with correctly labelled native controls, and
saving/organising user presets on the device.

## Phase status

### Phase 0 — Project setup — DONE

- Verified the APK against the handoff SHA-256 (exact match).
- Extracted all `assets/` (models, catalogs, preset, symbol tables) and the native
  libraries from the APK.
- Stood up a Python project: `src/firehawk/`, packaged data, tests, virtual env.

### Phase 1 — Model layer — DONE

- Parses all 11 `*.models` files into 261 typed models with full parameter metadata
  (name, range, value type, default).
- Self-calibrating decoder for `defaultSymbolTable.bin` (610/611 symbols, independently
  reproduces the shipped `firehawk_symbols.json`).
- Grouped pick-lists from the app's own `*Catalog.json` files, per slot.
- Signal-chain slot model (wah, compressor, gate, amp, cab, EQ, FX1–3, reverb, volume,
  global) with fixed vs. swappable slots and hardware-based model filtering.
- `EditBuffer` state model: validated writes (clamped to each parameter's range),
  model swapping with default reset, and change notifications for the UI/protocol.
- 32 passing tests.

### Phase 2 — Wire protocol (the one real unknown) — LARGELY SOLVED (static)

Goal: document the exact on-wire byte format so a "set parameter" (and preset recall,
block toggle, model change) message can be built without the native library.

Decompiled with Ghidra (see `docs/protocol.md`). **Confirmed:**
- **CRC-16/CCITT-FALSE** (poly 0x1021, init 0xFFFF, non-reflected).
- **Serial frame:** sync `0x55 0x55` + 12-byte header (seq/ack/length/payloadCRC/headerCRC)
  + payload; reliable seq/ack channel with 4-byte-aligned segments.
- **Transport header:** 8 bytes (type, addr-type 2, field, two port addresses).
- **Message body:** a key→value stream; 4-byte PSKey (addresses group+param) + TypedValue
  (2-byte type + value; continuous params are IEEE-754 floats); high-bit keys are
  slot/section directives.

**Remaining (fine detail):** the per-type TypedValue byte layout (jump table) and the
PSKey↔(group,param) numbering — both confirmable from **one Bluetooth HCI capture** of a
known edit (now trivial to interpret), or by decompiling the type jump table. Needs the
pedal + an Android device for the capture — a step Kaylea helps with.

### Phase 3 — Transport layer — DONE (offline path)

- `SerialTransport`: opens the paired pedal's Windows COM port with `pyserial`, with a
  background reader thread (mirrors the app's 64-byte inbound pump).
- `SimulatorTransport`: no-hardware transport that captures writes and can inject reads,
  so the whole app runs and is testable without the pedal.
- Port detection helpers (`list_serial_ports`, `find_firehawk_ports`).

### Phase 4 — Accessible UI (wxPython) — FIRST VERSION DONE

- Main window with a `Listbook` of the 12 signal-chain blocks; menu with local preset
  Open/Save/Reset and device-port detection.
- Per-block page: Enabled checkbox, Model chooser (grouped, deduped, testing groups
  hidden), and one labelled control per parameter — sliders (0..1 → 0..100), double
  spins (real-world ranges/units), integer spins (enums), checkboxes (booleans).
- Accessible names: sliders/spins/choices get a forced name via an attached
  `wx.Accessible` (`SetName` alone proved unreliable — some sliders read "slider 59");
  checkboxes carry their name in their **label**. Changing the model rebuilds the params.
- **High-contrast dark mode by default** (Settings > Dark Mode toggle) with large bold
  white labels, for low-vision use; visible selection highlight.
- **New Preset** (Ctrl+N) to start a fresh patch; **Save Preset** (Ctrl+S) to the user
  library; **Export to File**; **Escape** = two-level back (page controls → block list →
  Presets), **Ctrl+B** = Presets.
- **Only screen-reader-safe control types** are used: checkbox, slider, and dropdown.
  Spin/edit fields were dropped — they announce only their value to NVDA, never their
  label. Integer/enum params → dropdown; all continuous params → slider.
- **Unsaved-changes prompt** (Save / Discard / Cancel) before New, Open, Reset, or Close.
- **Help → Keyboard Commands (F1)** lists every shortcut.
- TODO: real named options for enum params (Mic, Note, Mixtype) from native tables.
- **Presets browser tab:** scrollable list of factory + user presets, a full read-only
  signal-chain summary of the selected preset, and Open / Save Current As / Delete /
  Refresh. Opening a preset loads it into the editor and jumps to the Amp page.
- **Jump hotkeys:** a "Go" menu reaches any page; Ctrl+1..Ctrl+9 jump to the first nine.
- **Settings menu:** user-presets folder location; device settings/modes info (pending
  the live connection).
- Verified headlessly (56 tests: pages build, no blank control names, checkboxes labelled,
  model swap/edit/JSON round-trip, preset open/save/delete) and by screenshot.
- **Still needs NVDA verification on the real machine** for the new checkbox labels and
  the Presets/Go navigation — Kaylea to confirm announcements.

### Phase 5 — Preset storage & studio features — PARTIAL

- Local preset library works now: factory + user presets, save/open/delete, with a full
  signal-chain summary — the offline equivalent of the old cloud download/save.
- Still to do: recall/store the pedal's on-device presets over the link; tuner; device
  settings; footswitch **modes**; tempo/tweak assignment wiring. (Depends on Phase 2.)

### Phase 6 — Hardening — NOT STARTED

- Reconnect handling, error surfacing, packaging as a runnable Windows app.

## How to run what exists today

```
# from the project root
.venv\Scripts\python -m firehawk           # launch the accessible app (or double-click Firehawk.bat)
.venv\Scripts\python -m pytest             # run the test suite (49 tests)
```
