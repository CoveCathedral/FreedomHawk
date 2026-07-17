"""Generate FreedomHawk starter presets into src/firehawk/presets/.

These are the project's own starting-point tones (not Line 6 factory presets, which
live on the pedal). Each is built through the validated EditBuffer so every model and
value is legal, then written as a standalone preset JSON that ships with the app.
"""

from __future__ import annotations

import json
from pathlib import Path

from firehawk.model import EditBuffer, ModelCatalog, Preset

OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "firehawk" / "presets"

# name, style, and per-block settings. Blocks omitted keep the default model.
# amp/cab/reverb/fx values are light overrides on top of each model's own defaults.
STARTERS = [
    dict(name="Pristine Clean", style="Clean",
         amp=("JazzClean", dict(Bass=0.55, Mid=0.5, Treble=0.6)),
         cab="2x12BlackfaceStudio", comp=True, gate=False,
         reverb=("HD_VerbzillaReverbHall", True, 0.28)),
    dict(name="Chime & Shimmer", style="Clean",
         amp=("ClassA30TopBoost", dict(Cut=0.6)),
         cab="2x12ClassAFawnStudio", comp=False, gate=False,
         fx3=("AnalogDelay", True, 0.18),
         reverb=("HD_VerbzillaReverbPlate", True, 0.3)),
    dict(name="Blues Breakup", style="Blues",
         amp=("TweedBMan", dict(Drive=0.55, Bass=0.5, Treble=0.55)),
         cab="1x12TweedStudio", comp=False, gate=False,
         reverb=("HD_VerbzillaReverbRoom", True, 0.2)),
    dict(name="Classic Crunch", style="Rock",
         amp=("BritGainJ800", dict(Drive=0.55, Bass=0.55, Mid=0.6, Treble=0.6, Presence=0.55)),
         cab="4x12BritT75Studio", comp=False, gate=True,
         reverb=("HD_VerbzillaReverbRoom", True, 0.15)),
    dict(name="Plexi Roar", style="Rock",
         amp=("BritPlexiLead100", dict(Drive=0.65, Presence=0.6)),
         cab="4x12BritT75Studio", comp=False, gate=True,
         reverb=("HD_VerbzillaReverbSpring", True, 0.18)),
    dict(name="Modern Metal", style="Metal",
         amp=("Line6ModernHiGain", dict(Drive=0.8, Bass=0.6, Mid=0.4, Treble=0.6)),
         cab="4x12BritT75Studio", comp=False, gate=True,
         reverb=("HD_VerbzillaReverbRoom", True, 0.1)),
    dict(name="Lead Machine", style="Lead",
         amp=("Solo100Head", dict(Drive=0.7, Mid=0.6, Presence=0.6)),
         cab="4x12BritT75Studio", comp=True, gate=True,
         fx3=("StereoDelay", True, 0.28),
         reverb=("HD_VerbzillaReverbHall", True, 0.22)),
    dict(name="Ambient Wash", style="Ambient",
         amp=("Line6Clean", dict(Bass=0.5, Treble=0.55)),
         cab="1x12Line6Studio", comp=False, gate=False,
         fx3=("AnalogDelay", True, 0.4),
         reverb=("HD_VerbzillaReverbHall", True, 0.5)),
    dict(name="Funk Rhythm", style="Funk",
         amp=("Line6Clean", dict(Bass=0.5, Mid=0.55, Treble=0.6)),
         cab="2x12Line6Studio", comp=True, gate=False,
         reverb=("HD_VerbzillaReverbRoom", True, 0.12)),
]


def build(cat: ModelCatalog, spec: dict) -> Preset:
    buf = EditBuffer(cat, Preset.load_default(cat.data_dir))
    buf.preset.meta = {
        "name": spec["name"], "author": "FreedomHawk", "band": "",
        "style": spec["style"], "instrument": "Electric",
    }
    amp_model, amp_params = spec["amp"]
    buf.set_model("amp", amp_model)
    for k, v in amp_params.items():
        buf.set_param("amp", k, v)
    buf.set_model("cab", spec["cab"])
    buf.set_enabled("compressor", spec.get("comp", False))
    buf.set_enabled("gate", spec.get("gate", False))
    # Disable the drive/mod fx by default; enable a delay only where specified.
    buf.set_enabled("fx1", False)
    buf.set_enabled("fx2", False)
    if "fx3" in spec:
        model, enabled, mix = spec["fx3"]
        buf.set_model("fx3", model)
        buf.set_enabled("fx3", enabled)
        buf.set_param("fx3", "@mix", mix)
    else:
        buf.set_enabled("fx3", False)
    rv_model, rv_on, rv_mix = spec["reverb"]
    buf.set_model("reverb", rv_model)
    buf.set_enabled("reverb", rv_on)
    buf.set_param("reverb", "@mix", rv_mix)
    return buf.preset


def main() -> int:
    cat = ModelCatalog()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, spec in enumerate(STARTERS, 1):
        preset = build(cat, spec)
        fn = OUT_DIR / f"{i:02d}_{spec['name'].lower().replace(' & ', '_').replace(' ', '_')}.json"
        fn.write_text(json.dumps(preset.to_json(), indent=2), encoding="utf-8")
        print(f"wrote {fn.name}: {spec['name']}  (amp {spec['amp'][0]})")
    print(f"\n{len(STARTERS)} starter presets written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
