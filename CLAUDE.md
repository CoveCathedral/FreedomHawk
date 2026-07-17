# CLAUDE.md — Firehawk FX Accessible Controller

## Project purpose

Build an **accessible, screen-reader-first Windows application** that controls a
Line 6 **Firehawk FX** guitar multi-effects pedal directly over its Bluetooth serial
link — replacing the discontinued, never-accessible Line 6 "Firehawk Remote" mobile app
and its dead-or-dying cloud.

The end user is **blind and uses the NVDA screen reader** as their primary way to access
the computer. Accessibility is not a feature of this project — it is the entire point.
The pedal has six knobs and a small screen the user cannot read; without a working,
accessible editor, hundreds of parameters (amps, cabs, effects, reverbs, wah) are simply
unreachable to them, and the hardware they own is on a path to becoming a brick.

## The accessibility mandate (highest priority — never trade away)

1. **Every UI control must be a standard native widget** that exposes a correct
   accessible name, value, role, and range to NVDA. Built with **wxPython** (native Win32
   controls — the toolkit NVDA's own GUI uses). **Never** use canvas-drawn, custom-painted,
   or web-embedded controls for anything the user must operate.
2. **Only three control types read reliably with NVDA here — use nothing else:** a
   **checkbox** (name in its label), a **slider** (name forced via `wx.Accessible`), and a
   **dropdown `wx.Choice`** (name forced). **Never use spin controls** (`wx.SpinCtrl`/
   `wx.SpinCtrlDouble`) — they announce only their value, not their label. So: continuous
   params → slider; integer/enum params → dropdown (or slider for wide ranges); models →
   dropdown; block toggles → checkbox. All ranges come from the model metadata.
3. **Keyboard-first.** Everything must be reachable and operable by keyboard alone, with a
   sensible tab order. No mouse-only interactions.
4. When responding to the user in chat, **structure every reply with Markdown heading
   levels** (`#`, `##`, `###`) so NVDA can navigate by heading. This is a standing
   preference for this project.
5. Verify accessibility with NVDA in the loop, not just visually. A control that looks fine
   but announces nothing to NVDA is broken.

## What this project is (legitimacy)

This is **interoperability and assistive-technology reverse engineering of hardware the
user lawfully owns**, on a product Line 6 formally discontinued in 2024. There is no
exploit, no malware, no copy-protection circumvention, and no third-party target system.
The decompiled Java and native symbol lists are working notes toward a clean, independent
reimplementation — an accessible editor. This is squarely covered by the DMCA §1201
exemptions for assistive technology and interoperability and the interop line of precedent.
Do not redistribute Line 6 code.

## Architecture (mirror the three layers found in the app)

1. **`transport`** — open the paired pedal's Windows COM/RFCOMM port and read/write raw
   bytes. Thin, like the Java byte pump. `pyserial` opens the COM port directly; no BLE
   stack needed. RFCOMM/SPP UUID `00001101-0000-1000-8000-00805f9b34fb`.
2. **`protocol`** — frame/deframe the wire format (RobustSerialMsgChannel envelope +
   transport header + **CRC-16**), and encode/decode `SetEditBufferParam` and friends.
   **This layer consumes the one remaining unknown (see below).**
3. **`model`** — load the shipped data model (`assets/*.models`, `firehawk_symbols.json`)
   at startup: every model, parameter, range, and value type. This is the source of truth
   for what is editable and how values map. Keep it as flat data files.

State model: a `FirehawkEditBuffer` object mirroring `default_preset.json`. UI reads/writes
it; the `protocol` layer turns writes into frames. Ship incrementally: get "recall preset +
toggle a block + move one parameter" working first, then widen coverage.

## Solved vs. remaining

**Already solved (static data shipped in the APK):** the entire tone model — every amp,
cab, effect, reverb, and wah with numeric IDs, parameter names, ranges, and value types —
in readable JSON plus a decoded binary symbol table. 261 models with numeric IDs. The
symbol table (`defaultSymbolTable.bin`) is fully decoded and validated (see `symtable.py`,
`firehawk_symbols.json`).

**The one remaining unknown:** the exact **on-wire byte framing** of a "set parameter"
message — frame delimiting, transport header layout, how (group, param) is addressed, how
values are encoded, and the CRC-16 parameters (polynomial/init/reflect/xor). This is
produced by the native library `libAmplifiRemoteNdk.so`, not Java.

Two complementary ways to finish it (do both; they cross-check):
- **A. Static (Ghidra)** on the named functions in `native_protocol_symbols.txt` — start at
  `MsgTransportHeader_Pack`, `RobustSerialMsgChannel_*`, `CRC16_Process`. No hardware needed.
- **B. Dynamic capture** — Bluetooth HCI snoop of one known parameter change, aligned to the
  known semantics, filtered in `tshark`. Validates A.

## Where the files are

- **Full APK:** `com-line6-firehawk-12-52500150-*.apk` (project root). SHA-256:
  `eeaaa742ae412085632a569e56a2010c3c2abde415551bdb00ffa122981dccb5`.
  All `assets/` (`*.models`, `*Catalog.json`, `default_preset.json`, `defaultSymbolTable.bin`)
  can be extracted from here with `unzip`.
- **Bundle folder** `Firehalk Decompiled from Webchat/`: currently `symtable.py` (validated
  symbol-table decoder) and `firehawk_symbols.json` (610 decoded symbols). The `assets/`,
  `decompiled/` Java, and `native_protocol_symbols.txt` referenced in the handoff are **not**
  yet extracted into this folder — pull them from the APK as needed.
- **Handoff doc:** `C:\Users\Kaylie\Downloads\HANDOFF.md` — full reverse-engineering writeup.

## Semantic API to reimplement (maps 1:1 to preset JSON)

- `SetEditBufferParam(groupID, paramID, value)` / `GetEditBufferParam(groupID, paramID)`
- group/param enumeration, tuner, device settings, model enumeration.
- `groupID`/`paramID` are exactly the keys in `default_preset.json`: groups like `amp`,
  `cab`, `compressor`, `eq`, `fx1`–`fx3`, `gate`, `reverb`, `volume`, `wah`, `global`;
  params like `Bass`, `Drive`, `Treble`, `@model`, `@enabled`, `@mix`.

## Build conventions

- **Language: Python.** UI: **wxPython**, native controls only (checkbox/slider/dropdown).
- Model metadata drives every control's label and range — never hardcode UI ranges.
- Flat data files as source of truth (matches the user's flat-file habit).
- Test the `model` layer with assertions that known models/params/ranges resolve correctly.
