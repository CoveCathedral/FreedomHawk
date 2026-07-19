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
    CORE_ROLES,
    ORNAMENTS,
    PATTERN_LIBRARY,
    LEVEL_ACCENT,
    LEVEL_GHOST,
    ROLE_LABELS,
    ROLES,
    RATE,
    DrumKit,
    Pattern,
    default_sample_for,
    list_role_files,
    load_sample,
    resample_pitch,
    scale_voice,
    steps_per_bar,
    synth_kit,
)
from .pitch import Pitch, estimate_pitch

#: Per-line pitch tuning is clamped to +/- two octaves.
MAX_TUNE = 24

#: Per-line volume trim, in decibels (0 = unchanged).  Down for ducking, a little up
#: for lift; full silence is the sample's "None" option, not the bottom of this range.
MIN_GAIN_DB, MAX_GAIN_DB = -24, 6

#: Choke groups a line can belong to (0 = none).  Lines sharing a group cut each
#: other's ring — the classic open-hat-closed-by-the-closed-hat behaviour.
MAX_CHOKE_GROUP = 4


def clamp_tune(value) -> int:
    """A line's tuning in whole semitones, clamped to the allowed range."""
    try:
        return max(-MAX_TUNE, min(MAX_TUNE, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def clamp_gain_db(value) -> int:
    """A line's volume trim in whole decibels, clamped to the allowed range."""
    try:
        return max(MIN_GAIN_DB, min(MAX_GAIN_DB, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def gain_from_db(db: float) -> float:
    """Linear amplitude multiplier for a decibel value (0 dB = 1.0)."""
    return 10.0 ** (db / 20.0)


def clamp_choke(value) -> int:
    """A line's choke-group number (0 = none), clamped to the allowed range."""
    try:
        return max(0, min(MAX_CHOKE_GROUP, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def choke_map(lines: list[dict]) -> dict:
    """Role/line-id -> choke group for the lines that belong to one (skips 0/none)."""
    return {ln["id"]: clamp_choke(ln.get("choke"))
            for ln in lines if clamp_choke(ln.get("choke"))}

MAX_LINES = 24  # keep the grid navigable

#: A line's `kit` field: None means "follow the globally selected kit"; this sentinel
#: means "explicitly the built-in synth"; any other string is an explicit kit folder.
SYNTH_KIT_NAME = "Synth (built-in)"

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
    """One line per part (ids match roles).  Lines follow the global kit (kit=None).

    Shows the parts the pattern actually uses plus a small core (kick/snare/hats), NOT
    every voice in the kit — the full standard kit has two dozen parts, and a wall of
    empty lines is a nightmare to arrow through.  The rest of the kit is one Add Line away.
    """
    wanted = set(pattern.hits) | set(CORE_ROLES)
    roles = [r for r in ROLES if r in wanted]
    roles += [r for r in pattern.hits if r not in roles]
    # Default hi-hat choke: when a groove actually plays both an open and a closed hat, put
    # them in one choke group so the closed hat cuts the open hat's ring (as on a real kit).
    # Keyed on the hits (not just kit voices), so closed-hat-only grooves are untouched.
    # The user can clear it per line with C in the editor.
    hats_choke = 1 if ("hihat" in pattern.hits and "openhat" in pattern.hits) else 0
    lines = []
    for role in roles:
        lines.append({
            "id": role, "label": ROLE_LABELS.get(role, role),
            "role": role if role in ROLES else "perc",
            "kit": None, "sample": None,  # follow the globally selected kit
            "steps": list(pattern.hits.get(role, [])),
            "choke": hats_choke if role in ("hihat", "openhat") else 0,
        })
    return lines


def lines_to_pattern(lines: list[dict], beats: int, unit: int, grid: int,
                     bars: int, name: str = "custom") -> Pattern:
    total = steps_per_bar(beats, unit, grid) * max(1, bars)
    hits = {}
    levels: dict = {}
    lengths: dict = {}
    probs: dict = {}
    ornaments: dict = {}
    for ln in lines:
        length = ln.get("length") or total  # per-line loop length (polymeter)
        steps = sorted(s for s in ln.get("steps", []) if 0 <= s < length)
        if not steps:
            continue
        hits[ln["id"]] = steps
        if length != total:
            lengths[ln["id"]] = length
        line_levels = {}
        for s in ln.get("accents", []):
            if s in steps:
                line_levels[s] = LEVEL_ACCENT
        for s in ln.get("ghosts", []):
            if s in steps:
                line_levels[s] = LEVEL_GHOST
        if line_levels:
            levels[ln["id"]] = line_levels
        line_probs = {}                  # JSON round-trips dict keys as strings
        for s_key, c in (ln.get("chances") or {}).items():
            try:
                s, c = int(s_key), int(c)
            except (TypeError, ValueError):
                continue
            if s in steps and 0 < c < 100:
                line_probs[s] = c
        if line_probs:
            probs[ln["id"]] = line_probs
        line_orns = {}
        for s_key, o in (ln.get("ornaments") or {}).items():
            try:
                s = int(s_key)
            except (TypeError, ValueError):
                continue
            if s in steps and o in ORNAMENTS:
                line_orns[s] = o
        if line_orns:
            ornaments[ln["id"]] = line_orns
    return Pattern(name, total, grid, hits, beats, unit, bars, levels, lengths,
                   probs=probs, ornaments=ornaments)


def resolve_line_voice(line: dict, kits_dir, base_kit: DrumKit | None,
                       synth: DrumKit | None = None, cache: dict | None = None):
    """The raw (untuned) voice a single line resolves to — its own kit/sample, else
    the global kit, else synth.  Shared by :func:`build_line_kit` and pitch readouts."""
    synth = synth or synth_kit()
    cache = cache if cache is not None else {}
    kit_name, role, sample = line.get("kit"), line.get("role"), line.get("sample")

    def global_voice(r):
        v = base_kit.voice(r) if base_kit else None
        return v if v is not None else synth.voice(r)

    if kit_name is None:                      # follow the globally selected kit
        return global_voice(role)
    if kit_name == SYNTH_KIT_NAME:            # explicitly synth
        return synth.voice(role)
    if kit_name not in cache:                 # an explicit sample kit folder
        cache[kit_name] = list_role_files(Path(kits_dir) / kit_name)
    files = cache[kit_name].get(role, [])
    path = next((f for f in files if f.name == sample), None) or default_sample_for(role, files)
    if path is not None:
        try:
            return load_sample(path)
        except Exception:  # noqa: BLE001
            pass
    return global_voice(role)                 # unreadable/missing -> fall back


def line_pitch(line: dict, kits_dir, base_kit: DrumKit | None = None) -> Pitch | None:
    """Estimate the musical pitch of a line's source sample (before any tuning)."""
    voice = resolve_line_voice(line, kits_dir, base_kit)
    if voice is None or len(voice) == 0:
        return None
    return estimate_pitch(voice, RATE, role=line.get("role"))


def build_line_kit(lines: list[dict], kits_dir, base_kit: DrumKit | None = None) -> DrumKit:
    """Voices for a line pattern: one per line id.

    Each line's source: ``kit=None`` follows *base_kit* (the globally selected kit),
    ``kit=SYNTH_KIT_NAME`` is the synth, any other name is that kit folder (with the
    line's own sample choice).  Each voice is pitch-shifted by the line's ``tune``
    (semitones) and scaled by its ``gain_db`` (volume trim).  Canonical roles missing
    from the lines fall back to the base kit (then synth), so generated fills sound.
    """
    synth = synth_kit()
    cache: dict = {}

    def global_voice(role: str):
        v = base_kit.voice(role) if base_kit else None
        return v if v is not None else synth.voice(role)

    voices: dict = {}
    for ln in lines:
        v = resolve_line_voice(ln, kits_dir, base_kit, synth, cache)
        if v is not None:
            v = resample_pitch(v, clamp_tune(ln.get("tune")))
            voices[ln["id"]] = scale_voice(v, gain_from_db(clamp_gain_db(ln.get("gain_db"))))
    for role in ROLES:  # fill/audition fallbacks for roles no line covers
        if role not in voices:
            voices[role] = global_voice(role)
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
        entry["chances"] = {str(s): c for s, c in
                            sorted(pattern.probs.get(ln["id"], {}).items())}
        entry["ornaments"] = {str(s): o for s, o in
                              sorted(pattern.ornaments.get(ln["id"], {}).items())}
        entry["length"] = pattern.lengths.get(ln["id"])  # None = default (synced)
        out_lines.append(entry)
    return {"name": name, "category": category, "beats": beats, "unit": unit,
            "grid": grid, "bars": bars, "lines": out_lines,
            "swing": round(float(pattern.swing), 4),
            "humanize": round(float(pattern.humanize), 4)}


def record_to_pattern(record: dict) -> Pattern:
    p = lines_to_pattern(record.get("lines", []), record.get("beats", 4),
                         record.get("unit", 4), record.get("grid", 4),
                         record.get("bars", 1), name=record.get("name", "custom"))
    p.swing = float(record.get("swing", 0.0) or 0.0)      # the groove's saved feel
    p.humanize = float(record.get("humanize", 0.0) or 0.0)
    return p


# -- songs: ordered chains of patterns (song mode / composition) -------------------

_SONG_KEY = "drum_songs"


def resolve_pattern_by_name(name: str, settings) -> Pattern | None:
    """Find a groove by name — a saved user pattern first, then the built-in library."""
    for rec in user_patterns(settings):
        if rec.get("name") == name:
            return record_to_pattern(rec)
    for p in PATTERN_LIBRARY:
        if p.name == name:
            return p
    return None


def normalize_section(s: dict) -> dict:
    """A song section as stored/edited: a groove name (or an inline tweaked pattern),
    a repeat count, and optional per-section tempo/kit/swing/fill overrides."""
    reps = max(0.5, round(float(s.get("repeats", 1)) * 2) / 2)  # halves allowed
    return {
        "pattern": str(s.get("pattern", "")),
        "repeats": int(reps) if reps == int(reps) else reps,
        "tempo": int(s["tempo"]) if s.get("tempo") else None,   # None = the song's tempo
        "kit": s.get("kit") or None,                            # None = the global kit
        # None = the groove's own saved swing; 0 is a real override (force straight).
        "swing": int(s["swing"]) if s.get("swing") is not None else None,
        "fill": s.get("fill") or None,          # None = as written; "improv" = generated
        "fill_amount": (int(s["fill_amount"])   # longer/busier improvised fills
                        if s.get("fill_amount") is not None else None),
        "inline": s.get("inline") or None,      # an edited-in-place pattern
    }


def make_song_record(name: str, sections: list, poly_tails: bool = False) -> dict:
    """A song record from section dicts (pattern/repeats/tempo/kit/inline).

    *poly_tails* saves the song-wide choice to let polymetric lines run past a
    section's end (default off: lines cut off at the boundary so the next section
    starts on its own count).
    """
    return {"name": name, "sections": [normalize_section(s) for s in sections],
            "poly_tails": bool(poly_tails)}


def resolve_section_pattern(section: dict, settings) -> Pattern | None:
    """The Pattern a section plays: its inline (edited) pattern if any, else by name."""
    inline = section.get("inline")
    if inline:
        return record_to_pattern(inline)
    return resolve_pattern_by_name(str(section.get("pattern", "")), settings)


def inline_record_from_pattern(pattern: Pattern, kit=None, kit_name: str | None = None,
                               base_record: dict | None = None) -> dict:
    """Serialize a Pattern into a section's inline record (so a song-wide beat edit can be
    stored back on the section without touching the shared library groove).

    Pass *base_record* — the section's existing inline — to **preserve every per-line
    property the Pattern can't hold** (a line's kit/sample source, tune, volume, choke).
    Only the hits, dynamics, chances, ornaments and lengths (what the beat editor actually
    changes) are taken from *pattern*; a part the edit newly introduced gets a fresh line.
    Without a base record, the lines are derived fresh from the pattern's parts.
    """
    if base_record and base_record.get("lines"):
        lines = [dict(ln) for ln in base_record["lines"]]
        have = {ln.get("id") for ln in lines}
        for role in pattern.hits:                    # a part Add Line introduced
            if role not in have:
                lines.append({"id": role, "label": ROLE_LABELS.get(role, role),
                              "role": role if role in ROLES else "perc",
                              "kit": None, "sample": None, "steps": []})
    else:
        lines = lines_for_kit(pattern, kit, kit_name)
    return make_record(pattern.name or "section", "Song", pattern.beats_per_bar,
                       pattern.beat_unit, pattern.steps_per_beat, pattern.bars,
                       lines, pattern)


def split_section_repeat(sections: list, index: int, repeat: int,
                         settings=None) -> tuple[list, int]:
    """Split ``sections[index]`` so its ``repeat``-th pass (0-based) becomes its own
    one-repeat section, carrying an **inline copy** of the pattern so editing that repeat
    alone never touches the others.  Returns ``(new_sections, variant_index)`` — the index
    of the split-off section in the new list.  The repeats before and after keep the
    original groove reference and play exactly as they did.
    """
    s = sections[index]
    reps = max(0.5, round(float(s.get("repeats", 1)) * 2) / 2)   # halves preserved
    whole = int(reps)
    frac = reps - whole                                          # 0 or 0.5
    if whole < 1:                                                # nothing to split off
        return list(sections), index
    # Valid repeat indices are the whole repeats 0..whole-1, plus the fractional tail
    # (index == whole) when there is a half — so a cursor sitting in the .5 tail splits
    # THAT half off, not the last whole repeat.
    tail = whole if frac > 0 else -1
    repeat = max(0, min(whole - 1 if frac == 0 else whole, int(repeat)))
    pattern = resolve_section_pattern(s, settings)

    variant = dict(s)
    if pattern is not None:
        variant["inline"] = inline_record_from_pattern(pattern, base_record=s.get("inline"))
    if repeat == tail:                          # split the fractional tail off (a 0.5 section)
        before_reps, variant["repeats"], after_reps = whole, frac, 0
    else:
        before_reps, variant["repeats"] = repeat, 1
        after_reps = (whole - repeat - 1) + frac
    before = dict(s, repeats=before_reps)
    after = dict(s, repeats=int(after_reps) if after_reps == int(after_reps) else after_reps)

    out = list(sections[:index])
    if before_reps > 0:
        out.append(before)
    variant_index = len(out)
    out.append(variant)
    if after_reps > 0:
        out.append(after)
    out.extend(sections[index + 1:])
    return out, variant_index


def song_sections(record: dict, settings) -> list:
    """Resolve to ``[(Pattern, repeats, tempo, kit_name), ...]``; skip missing patterns."""
    out = []
    for s in record.get("sections", []):
        pattern = resolve_section_pattern(s, settings)
        if pattern is not None:
            out.append((pattern, max(0.5, round(float(s.get("repeats", 1)) * 2) / 2),
                        s.get("tempo"), s.get("kit")))
    return out


def user_songs(settings) -> list[dict]:
    if settings is None:
        return []
    return list(settings.get(_SONG_KEY) or [])


def save_song(settings, record: dict) -> None:
    """Add or replace (by name) a saved song."""
    if settings is None:
        return
    records = [r for r in user_songs(settings) if r.get("name") != record.get("name")]
    records.append(record)
    settings.set(_SONG_KEY, records)


def delete_song(settings, name: str) -> bool:
    records = user_songs(settings)
    kept = [r for r in records if r.get("name") != name]
    if len(kept) == len(records):
        return False
    settings.set(_SONG_KEY, kept)
    return True


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
        length = ln.get("length")
        if isinstance(length, (int, float)) and 1 <= int(length) <= 64:
            length = int(length)
        else:
            length = None
        limit = length or total
        steps = sorted({int(s) for s in ln.get("steps", [])
                        if isinstance(s, (int, float)) and 0 <= int(s) < limit})

        def _level_steps(key):
            return sorted({int(s) for s in ln.get(key, [])
                           if isinstance(s, (int, float)) and int(s) in steps})
        lines.append({
            "id": str(ln["id"]), "label": str(ln.get("label") or ln["id"]),
            "role": role, "kit": (str(ln["kit"]) if ln.get("kit") else None),
            "sample": (str(ln["sample"]) if ln.get("sample") else None),
            "steps": steps, "length": length, "tune": clamp_tune(ln.get("tune")),
            "gain_db": clamp_gain_db(ln.get("gain_db")), "choke": clamp_choke(ln.get("choke")),
            "accents": _level_steps("accents"), "ghosts": _level_steps("ghosts"),
        })
    if not lines:
        raise ValueError("the pattern's lines are unreadable")
    return {"name": name, "category": str(data.get("category") or "Imported"),
            "beats": beats, "unit": unit, "grid": grid, "bars": bars, "lines": lines}
