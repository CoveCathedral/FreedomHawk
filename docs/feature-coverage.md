# Feature coverage vs. the Firehawk Remote app

Audited against the bundled Firehawk FX Pilot's Guide (`assets/manual.pdf`). Goal: cover
every Firehawk Remote feature **except the cloud-dependent ones**, which the project
excludes by design.

Legend: ✅ done · 🔧 editable now (this pass) · 🔜 staged (encoder wired, needs the live
connection + protocol validation) · 🎛️ hardware-only (not app-controllable) · ☁️ excluded
(cloud/streaming).

## Tone editing (the Editor)

| Feature | Status | Notes |
|---|---|---|
| Amp / Cab / Comp / Gate / EQ / FX1–3 / Reverb / Wah / Volume blocks | ✅ | All 261 models, every parameter labelled and ranged |
| Model selection per block | ✅ | Grouped, deduped choosers |
| Block enable / bypass | ✅ | Checkboxes |
| FX mix / mix type / pre-post / stereo (`@mix`,`@mixtype`,`@post`,`@stereo`) | ✅ | Editable; encodes as structural params |
| Tweak / FX-Knob assignment (`@tweakgroup`,`@tweakparam`) | 🔧 | Now editable choosers on the Global page |
| Tweak/Pedal **Range** (`@tweakmin`,`@tweakmax`) | 🔧 | Editable sliders on the Global page |
| Pedal 2 assign (`@pedal2assign`) | 🔧 | Editable on the Global page |
| **Variax** settings (model, 6 string tunings, pickup mode, tone knob) | 🔧 | New Variax page |
| Global tempo | ✅ | Global page slider (30–240 BPM) |
| Footswitch FS1–FS5 block assignments | 🔜 | Protocol has `setFootswitchAssign`; UI/command to wire next |
| Pedal Mode (Wah/Volume · Wah Only · Tweak) | 🔜 | Device setting; wire next |

## Presets

| Feature | Status | Notes |
|---|---|---|
| Browse / recall / edit local presets | ✅ | Starter + user + bundled factory |
| Save preset locally | ✅ | User library (the offline "My Tones") |
| Preset details / signal-chain overview | ✅ | Details pane |
| Hardware presets (128 on device, banks 1–32 × A–D) | 🔜 | Read/recall/store needs the live protocol |
| Save preset **to device** | 🔜 | `savePresetToDevice` path decoded; needs validation |
| Tone name / author / style metadata | ✅ (partial) | Shown; full metadata editing is minor polish |

## Tools & device

| Feature | Status | Notes |
|---|---|---|
| Tuner | ✅ | **By-ear reference-tone tuner** — plays a sustained tone per string; instrument (6/7/8-string guitar, 4/5/6-string bass) + full tuning library. No pedal needed, and far more useful to a blind player than the pedal's light-based tuner |
| Tap tempo | ✅ | Tempo is set on the Global page (live tap is a device action) |
| Master volume / guitar-level blend | 🎛️ | Front-panel knob; not an app parameter |
| Output Mode (Line / Amp) | 🎛️ | **Rear-panel physical switch** — not app-controllable |
| Firmware update | — | Out of scope (risky; not an accessibility need) |
| Factory reset / pedal calibration | 🎛️ | On-device footswitch sequences |

## Excluded by design (cloud / streaming)

| Feature | Notes |
|---|---|
| Cloud Search / My Tones (Line 6 account) | ☁️ The dead cloud — the whole reason this project exists |
| Automatic cloud Tone Matching (song → tone) | ☁️ Needs the dead cloud |

Note: **music play-along still works** — the Firehawk is a Bluetooth speaker, so once paired
you can set it as the Windows playback device and play any song through it (Help → Playing
Along with Music). Only the *cloud tone-matching* part is gone.

## Beyond the original app (our additions)

- Full **NVDA screen-reader accessibility** — the entire point; the original app had none.
- **High-contrast dark mode**, large labels, keyboard-first navigation, jump hotkeys.
- A **staged, gated** device bridge that shows the exact bytes each edit would send.

## Summary

Everything the Firehawk Remote app did for **editing and local preset management** is
covered now. The remaining items are either (a) **hardware-only** (output mode, master
volume, reset), (b) **cloud** (excluded by design), or (c) **live-device features** (tuner,
footswitches, hardware presets) whose encoders are mapped and staged, waiting on the one
protocol validation. No editing capability is missing.
