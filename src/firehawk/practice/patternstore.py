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
    LEVEL_ACCENT,
    LEVEL_GHOST,
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
    levels: dict = {}
    for ln in lines:
        steps = sorted(s for s in ln.get("steps", []) if 0 <= s < total)
        if not steps:
            continue
        hits[ln["id"]] = steps
        line_levels = {}
        for s in ln.get("accents", []):
            if s in steps:
                line_levels[s] = LEVEL_ACCENT
        for s in ln.get("ghosts", []):
            if s in steps:
                line_levels[s] = LEVEL_GHOST
        if line_levels:
            levels[ln["id"]] = line_levels
    return Pattern(name, total, grid, hits, beats, unit, bars, levels)


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
    """Serialize the editor state; each line carries its steps and dynamics."""
    out_lines = []
    for ln in lines:
        entry = dict(ln)
        entry["steps"] = list(pattern.hits.get(ln["id"], []))
        line_levels = pattern.levels.get(ln["id"], {})
        entry["accents"] = sorted(s for s, lv in line_levels.items() if lv == LEVEL_ACCENT)
        entry["ghosts"] = sorted(s for s, lv in line_levels.items() if lv == LEVEL_GHOST)
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


# -- library management (the category/pattern manager) -----------------------------

def delete_pattern(settings, name: str) -> bool:
    records = user_patterns(settings)
    kept = [r for r in records if r.get("name") != name]
    if len(kept) == len(records):
        return False
    settings.set(_STORE_KEY, kept)
    return True

def rename_pattern(settings, old_name: str, new_name: str) -> bool:
    new_name = new_name.strip()
    if not new_name:
        return False
    records = user_patterns(settings)
    if any(r.get("name") == new_name for r in records):
        return False  # names are the store key; keep them unique
    changed = False
    for r in records:
        if r.get("name") == old_name:
            r["name"] = new_name
            changed = True
    if changed:
        settings.set(_STORE_KEY, records)
    return changed

def set_pattern_category(settings, name: str, category: str) -> bool:
    records = user_patterns(settings)
    changed = False
    for r in records:
        if r.get("name") == name:
            r["category"] = category.strip() or "My patterns"
            changed = True
    if changed:
        settings.set(_STORE_KEY, records)
    return changed

def rename_category(settings, old: str, new: str) -> int:
    """Rename a user category on every pattern in it; returns how many changed."""
    new = new.strip()
    if not new:
        return 0
    records = user_patterns(settings)
    count = 0
    for r in records:
        if r.get("category") == old:
            r["category"] = new
            count += 1
    if count:
        settings.set(_STORE_KEY, records)
    return count


# -- pattern file import/export (shareable JSON) -----------------------------------

_FILE_FORMAT = "freedomhawk-drum-pattern"
_FILE_VERSION = 1

def record_to_file_dict(record: dict) -> dict:
    """A saved pattern as a self-describing, shareable JSON document."""
    return {"format": _FILE_FORMAT, "version": _FILE_VERSION, **record}

def record_from_file_dict(data: dict) -> dict:
    """Validate an imported pattern document and return a clean record.

    Raises ValueError with a human-readable reason on anything malformed.
    """
    if not isinstance(data, dict) or data.get("format") != _FILE_FORMAT:
        raise ValueError("not a FreedomHawk drum pattern file")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("the pattern has no name")
    try:
        beats = int(data.get("beats", 4))
        unit = int(data.get("unit", 4))
        grid = int(data.get("grid", 4))
        bars = int(data.get("bars", 1))
    except (TypeError, ValueError):
        raise ValueError("the pattern's meter values are not numbers") from None
    if not (1 <= beats <= 16 and unit in (2, 4, 8, 16)
            and 1 <= grid <= 4 and 1 <= bars <= 4):
        raise ValueError("the pattern's meter is out of range")
    lines_in = data.get("lines")
    if not isinstance(lines_in, list) or not lines_in:
        raise ValueError("the pattern has no lines")
    total = steps_per_bar(beats, unit, grid) * bars
    lines: list[dict] = []
    for ln in lines_in[:MAX_LINES]:
        if not isinstance(ln, dict) or not ln.get("id"):
            continue
        role = ln.get("role") if ln.get("role") in ROLES else "perc"
        steps = sorted({int(s) for s in ln.get("steps", [])
                        if isinstance(s, (int, float)) and 0 <= int(s) < total})

        def _level_steps(key):
            return sorted({int(s) for s in ln.get(key, [])
                           if isinstance(s, (int, float)) and int(s) in steps})
        lines.append({
            "id": str(ln["id"]), "label": str(ln.get("label") or ln["id"]),
            "role": role, "kit": (str(ln["kit"]) if ln.get("kit") else None),
            "sample": (str(ln["sample"]) if ln.get("sample") else None),
            "steps": steps,
            "accents": _level_steps("accents"), "ghosts": _level_steps("ghosts"),
        })
    if not lines:
        raise ValueError("the pattern's lines are unreadable")
    return {"name": name, "category": str(data.get("category") or "Imported"),
            "beats": beats, "unit": unit, "grid": grid, "bars": bars, "lines": lines}
