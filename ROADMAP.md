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

### Phase 2.5 — UI ↔ protocol wiring — STAGED (gated, no transmission yet)

- `firehawk.device.DeviceSession` subscribes to edit-buffer changes and routes each one
  to the right ToneMatch command via `protocol.addressing.encode_edit`, mirroring the
  pedal's own `sendParamToDevice`: model knobs, structural (@) params, tempo, model load,
  and global psKey params each have a corresponding path.
- Every edit is encoded and logged to an outbox (viewable in **Device → View Outgoing
  Messages**), so you can see the exact bytes each control *would* send — ready to diff
  against a real capture.
- **Safety gate:** `transmit_enabled` is off by default; enabling it requires confirming a
  warning. Device menu adds Connect, the transmit toggle, and the message viewer.
- 87 passing tests, incl. dispatch-per-type, the safety gate, and frame round-trip.

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

### Phase 7 — Practice tools & app-only features (beyond the original app) — IN PROGRESS

Features the Firehawk Remote app never had, made possible by being a Windows-native app.
All screen-reader-first, native controls only.

- **By-ear tuner** — DONE. Sustained reference tone per string; instrument (6/7/8-string
  guitar, 4/5/6-string bass) + full tuning library. Far more useful to a blind player than
  the pedal's light-based tuner.
- **Metronome** — DONE. Tempo 30–300 BPM (announced as real BPM, not a percentage), time
  signature incl. **odd/prog meters** with accent grouping (e.g. 2+2+3 for 7/8), subdivision,
  tap-tempo. Synthesized clicks; keeps running across tabs.
- **Drum Looper** — DONE, several iterations with Kaylea live-testing. Built-in synth kit
  (kick/snare/hats/clap/808/tom/perc/ride/crash) or user drum libraries (Import Drum Kit
  button; kits auto-discovered from `Samples/`; per-part sample choice via Kit Sounds).
  **200-groove library** + **user-saved patterns** with genre **categories and filtering**
  (user-defined categories included). **Tracker-grid Pattern Editor** (Kaylea's design):
  one list line per drum line, spoken time cursor (step/beat/bar granularity via direct
  screen-reader speech), Space toggles, Enter per-line sample options incl. None, Delete,
  P preview, F1 key help; **drum stacking + mix-and-match across libraries** (up to 24
  lines); Add Line / Load Groove / Save as Preset; **Ctrl+D** opens a blank editor from
  anywhere. **Improvised fills** (rule-bound randomness, meter-aware, fill-every-N up to
  16 bars) and a drum master volume. Loop is pre-mixed so any-length sample lands exactly
  on the beat (`practice/drums.py`, `patternstore.py`); numpy + accessible_output2.
  **Sharing & management (Tools menu):** Drum Pattern Library manager (rename/delete/
  recategorize patterns, rename categories); WAV export of the playing loop; shareable
  pattern files (`.fhdrum.json`) import/export; **MIDI export/import** (GM drum channel,
  meter-aware, dependency-free SMF in `practice/midifile.py`). See `docs/drum-kits.md`.
  **Feel:** per-hit dynamics (accent/ghost, Space-cycled and spoken; baked into all 200
  library grooves), **swing/shuffle**, and **humanize** — all through the whole pipeline
  (render, transforms, improviser, saves, MIDI velocities). **Per-line polymeter**
  (`-`/`+` set each line's own loop length; parts phase and realign over the LCM,
  `flatten_polymeter`; shared pulse; saved + exported).
  **Planned next (Kaylea approved):** song mode (pattern chaining) · per-line tuning
  (808 to key) · tempo trainer · count-in · audition-step & speak-rhythm keys · choke
  groups · **MIDI controller input** (craft beats from a keyboard). Long-term: spin
  the sequencer out as its own open-source project (engine already firehawk-independent).
- **Customizable tab order** — DONE. Settings → Arrange Tabs (Alt+Up/Down); persists to
  `%APPDATA%/FreedomHawk/settings.json`. Practice tools default to the bottom.
- **Queued (sequenced next):** Setlist / gig mode (ordered presets, Next/Prev hotkeys;
  later drives footswitch recall) · A/B tone compare · full signal-chain readout hotkey.

### Phase 6 — Hardening — NOT STARTED

- Reconnect handling, error surfacing, packaging as a runnable Windows app.

## How to run what exists today

```
# from the project root
.venv\Scripts\python -m firehawk           # launch the accessible app (or double-click Firehawk.bat)
.venv\Scripts\python -m pytest             # run the test suite (191 tests)
```

User documentation: `docs/user-manual.md` (the manual), `docs/drum-kits.md` (drum machine
guide), plus in-app Help (F1 and the Help menu).
