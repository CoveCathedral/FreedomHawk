"""Pattern lines, mix-and-match voices, and the user's saved drum patterns.

A drum pattern in the editor is a list of **lines**.  Each line is a plain dict:

    {"id": "kick 2", "label": "Kick 2 (Bloodlust Drumkit)", "role": "kick",
     "kit": "Bloodlust Drumkit" | None, "sample": "740 KICK ;P.wav" | None,
     "steps": [0, 8]}

``kit`` of None means the built-in synth voice for the role; otherwise the sample
comes from that kit folder's role subfolder (``sample`` of None = automatic pick).
Lines are independent, so a pattern can stack several lines of the same role and
mix sources freely — synth kick, Bloodlust snare, a friend's crash.

Saved patterns (name + category + meter + lines) persist as JSON via AppSettings
under the key ``drum_patterns`` and appear in the Groove list next to the built-ins.
"""

from __future__ import annotations

from pathlib import Path

from .drums import (
    GENRE_PATTERNS,
    ROLE_LABELS,
    ROLES,
    DrumKit,
    Pattern,
    default_sample_for,
    list_role_files,
    load_sample,
    steps_per_bar,
    synth_kit,
)

MAX_LINES = 24  # keep the grid navigable

_STORE_KEY = "drum_patterns"


# -- lines <-> pattern -------------------------------------------------------------

def make_line(role: str, kit: str | None = None, sample: str | None = None,
              existing: list | None = None) -> dict:
    """A new line dict with a unique id and a descriptive label."""
    ids = {ln["id"] for ln in (existing or [])}
    n, line_id = 1, role
    while line_id in ids:
        n += 1
        line_id = f"{role} {n}"
    label = ROLE_LABELS.get(role, role) + (f" {n}" if n > 1 else "")
    if kit:
        label += f" ({kit})"
    return {"id": line_id, "label": label, "role": role, "kit": kit,
            "sample": sample, "steps": []}


def lines_for_kit(pattern: Pattern, kit, kit_name: str | None,
                  sample_choices: dict | None = None) -> list[dict]:
    """One line per part for an ordinary single-kit pattern (ids match roles)."""
    kit_roles = kit.roles() if kit else []
    roles = [r for r in ROLES if r in kit_roles or r in pattern.hits]
    roles += [r for r in pattern.hits if r not in roles]
    lines = []
    for role in roles:
        lines.append({
            "id": role, "label": ROLE_LABELS.get(role, role),
            "role": role if role in ROLES else "perc",
            "kit": kit_name, "sample": (sample_choices or {}).get(role),
            "steps": list(pattern.hits.get(role, [])),
        })
    return lines


def lines_to_pattern(lines: list[dict], beats: int, unit: int, grid: int,
                     bars: int, name: str = "custom") -> Pattern:
    total = steps_per_bar(beats, unit, grid) * max(1, bars)
    hits = {}
    for ln in lines:
        steps = sorted(s for s in ln.get("steps", []) if 0 <= s < total)
        if steps:
            hits[ln["id"]] = steps
    return Pattern(name, total, grid, hits, beats, unit, bars)


def build_line_kit(lines: list[dict], kits_dir, base_kit: DrumKit | None = None) -> DrumKit:
    """Voices for a line pattern: one per line id, each from its own source.

    Canonical roles missing from the lines fall back to the base kit (then synth),
    so generated fills — snare, tom, crash — always sound.
    """
    synth = synth_kit()
    voices: dict = {}
    cache: dict = {}
    for ln in lines:
        role, kit_name, sample = ln.get("role"), ln.get("kit"), ln.get("sample")
        voice = None
        if kit_name:
            if kit_name not in cache:
                cache[kit_name] = list_role_files(Path(kits_dir) / kit_name)
            files = cache[kit_name].get(role, [])
            path = next((f for f in files if f.name == sample), None)
            if path is None:
                path = default_sample_for(role, files)
            if path is not None:
                try:
                    voice = load_sample(path)
                except Exception:  # noqa: BLE001 - fall back to synth below
                    voice = None
        if voice is None:
            voice = synth.voice(role)
        if voice is not None:
            voices[ln["id"]] = voice
    for role in ROLES:  # fill/audition fallbacks for roles no line covers
        if role not in voices:
            voice = base_kit.voice(role) if base_kit else None
            if voice is None:
                voice = synth.voice(role)
            if voice is not None:
                voices[role] = voice
    return DrumKit("custom", voices)


# -- built-in categories -----------------------------------------------------------

def builtin_category(name: str) -> str:
    """The genre family of a built-in groove ('Rock 04 fill' -> 'Rock')."""
    best = ""
    for base in GENRE_PATTERNS:
        if name.startswith(base.name) and len(base.name) > len(best):
            best = base.name
    return best or name


# -- the saved-pattern store (via AppSettings) -------------------------------------

def user_patterns(settings) -> list[dict]:
    if settings is None:
        return []
    return list(settings.get(_STORE_KEY) or [])


def save_user_pattern(settings, record: dict) -> None:
    """Add or replace (by name) a saved pattern record."""
    if settings is None:
        return
    records = [r for r in user_patterns(settings) if r.get("name") != record.get("name")]
    records.append(record)
    settings.set(_STORE_KEY, records)


def make_record(name: str, category: str, beats: int, unit: int, grid: int,
                bars: int, lines: list[dict], pattern: Pattern) -> dict:
    """Serialize the editor state; each line carries its steps from *pattern*."""
    out_lines = []
    for ln in lines:
        entry = dict(ln)
        entry["steps"] = list(pattern.hits.get(ln["id"], []))
        out_lines.append(entry)
    return {"name": name, "category": category, "beats": beats, "unit": unit,
            "grid": grid, "bars": bars, "lines": out_lines}


def record_to_pattern(record: dict) -> Pattern:
    return lines_to_pattern(record.get("lines", []), record.get("beats", 4),
                            record.get("unit", 4), record.get("grid", 4),
                            record.get("bars", 1), name=record.get("name", "custom"))


def all_categories(settings) -> list[str]:
    """Every category: the built-in genre families plus the user's own."""
    cats = {p.name for p in GENRE_PATTERNS}
    for rec in user_patterns(settings):
        if rec.get("category"):
            cats.add(rec["category"])
    return sorted(cats)
