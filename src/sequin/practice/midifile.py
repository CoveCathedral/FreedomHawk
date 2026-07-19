"""MIDI file export/import for drum patterns (no external dependencies).

Export writes a Standard MIDI File (format 0) with the pattern on the General MIDI
drum channel (10), so a groove made here opens in any DAW with any drum sounds.
Import reads a .mid file, takes its drum-channel notes (falling back to all notes
if the file has no drum channel), maps General MIDI drum numbers onto our roles,
and quantizes onto the step grid.
"""

from __future__ import annotations

import struct

from .drums import LEVEL_ACCENT, LEVEL_GHOST, MAX_STEPS, ROLES, Pattern, steps_per_bar

_TICKS_PER_QUARTER = 480
_DRUM_CHANNEL = 9  # zero-based channel 10

#: Dynamics <-> MIDI velocity. Import thresholds sit between the export values so
#: our own files round-trip exactly and foreign files classify sensibly.
_LEVEL_VELOCITY = {LEVEL_ACCENT: 120, None: 90, LEVEL_GHOST: 45}
_GHOST_BELOW = 60
_ACCENT_ABOVE = 105

#: Our roles -> General MIDI percussion note numbers (full standard kit).
ROLE_TO_GM = {
    "kick": 36, "snare": 38, "rimshot": 37, "clap": 39,
    "hihat": 42, "pedalhat": 44, "openhat": 46,
    "tom1": 50, "tom2": 48, "tom": 47, "tom4": 45, "tom5": 43,
    "crash": 49, "crash2": 57, "splash": 55, "china": 52,
    "ride": 51, "ridebell": 53,
    "cowbell": 56, "tambourine": 54, "shaker": 70,
    "808": 35, "perc": 75, "fx": 76,
}

#: General MIDI percussion note numbers -> our roles.  Every standard GM drum note lands
#: on the closest part of the full kit; unlisted notes fall through to perc on import.
GM_TO_ROLE = {
    35: "kick", 36: "kick",
    37: "rimshot", 39: "clap",
    38: "snare", 40: "snare",
    42: "hihat", 44: "pedalhat", 46: "openhat",
    41: "tom5", 43: "tom5", 45: "tom4", 47: "tom", 48: "tom2", 50: "tom1",
    49: "crash", 57: "crash2", 55: "splash", 52: "china",
    51: "ride", 59: "ride", 53: "ridebell",
    56: "cowbell", 54: "tambourine", 70: "shaker", 82: "shaker",
    75: "perc", 76: "perc", 77: "perc",
}


def _vlq(value: int) -> bytes:
    """A MIDI variable-length quantity."""
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def pattern_to_midi(pattern: Pattern, bpm: float,
                    role_of: dict[str, str] | None = None) -> bytes:
    """One loop of *pattern* as a format-0 MIDI file on the drum channel."""
    ticks_per_step = max(1, _TICKS_PER_QUARTER // max(1, pattern.steps_per_beat))
    events: list[tuple[int, bytes]] = []
    for line_id, steps in pattern.hits.items():
        role = (role_of or {}).get(line_id, line_id if line_id in ROLES else "perc")
        note = ROLE_TO_GM.get(role, 37)
        line_levels = pattern.levels.get(line_id, {})
        for step in steps:
            tick = step * ticks_per_step
            velocity = _LEVEL_VELOCITY.get(line_levels.get(step), 90)
            events.append((tick, bytes((0x90 | _DRUM_CHANNEL, note, velocity))))
            events.append((tick + ticks_per_step // 2, bytes((0x80 | _DRUM_CHANNEL, note, 0))))
    events.sort(key=lambda e: e[0])

    track = bytearray()
    # Tempo and time signature so DAWs read the meter correctly.
    track += b"\x00\xff\x51\x03" + int(60_000_000 / max(1.0, bpm)).to_bytes(3, "big")
    denom_power = max(1, pattern.beat_unit).bit_length() - 1
    track += b"\x00\xff\x58\x04" + bytes((pattern.beats_per_bar, denom_power, 24, 8))
    last_tick = 0
    for tick, msg in events:
        track += _vlq(tick - last_tick) + msg
        last_tick = tick
    end_tick = pattern.steps * ticks_per_step
    track += _vlq(max(0, end_tick - last_tick)) + b"\xff\x2f\x00"

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, _TICKS_PER_QUARTER)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def _read_vlq(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos


def _parse_notes(data: bytes):
    """All note-on events as (tick, channel, note), plus any time signature found."""
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    _length, fmt, ntracks, division = struct.unpack(">IHHH", data[4:14])
    if fmt not in (0, 1):
        raise ValueError(f"unsupported MIDI format {fmt}")
    if division & 0x8000:
        raise ValueError("SMPTE-timed MIDI files are not supported")
    notes: list[tuple[int, int, int]] = []
    timesig: tuple[int, int] | None = None
    pos = 14
    for _ in range(ntracks):
        if data[pos:pos + 4] != b"MTrk":
            break
        (tlen,) = struct.unpack(">I", data[pos + 4:pos + 8])
        p, end = pos + 8, pos + 8 + tlen
        tick = 0
        status = 0
        while p < end:
            delta, p = _read_vlq(data, p)
            tick += delta
            byte = data[p]
            if byte & 0x80:
                status = byte
                p += 1
            if status == 0xFF:  # meta
                meta = data[p]
                mlen, p2 = _read_vlq(data, p + 1)
                if meta == 0x58 and mlen >= 2 and timesig is None:
                    timesig = (data[p2], 1 << data[p2 + 1])
                p = p2 + mlen
            elif status in (0xF0, 0xF7):  # sysex
                slen, p2 = _read_vlq(data, p)
                p = p2 + slen
            else:
                kind = status & 0xF0
                if kind in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    if kind == 0x90 and data[p + 1] > 0:
                        notes.append((tick, status & 0x0F, data[p], data[p + 1]))
                    p += 2
                elif kind in (0xC0, 0xD0):
                    p += 1
                else:
                    raise ValueError("corrupt MIDI track data")
        pos = end
    return notes, timesig, division


def midi_to_pattern(data: bytes, grid: int = 4) -> tuple[Pattern, dict]:
    """A .mid file's drum notes quantized onto our grid.

    Returns (pattern, info); info notes anything lossy (no drum channel found,
    hits beyond the 4-bar cap dropped, unmapped notes counted as perc).
    """
    notes, timesig, division = _parse_notes(data)
    if not notes:
        raise ValueError("the MIDI file contains no notes")
    info: dict = {"notes": len(notes)}
    drum_notes = [n for n in notes if n[1] == _DRUM_CHANNEL]
    if drum_notes:
        notes = drum_notes
    else:
        info["no_drum_channel"] = True  # melodic file: map everything as best we can
    beats, unit = timesig or (4, 4)
    beats = max(1, min(16, beats))
    unit = unit if unit in (2, 4, 8, 16) else 4
    ticks_per_step = max(1, division // max(1, grid))
    per_bar = steps_per_bar(beats, unit, grid)
    hits: dict[str, set] = {}
    velocities: dict = {}  # (role, step) -> max velocity seen
    max_step = 0
    for tick, _ch, note, velocity in notes:
        step = round(tick / ticks_per_step)
        role = GM_TO_ROLE.get(note)
        if role is None:
            role = "perc"
            info["unmapped"] = info.get("unmapped", 0) + 1
        hits.setdefault(role, set()).add(step)
        velocities[(role, step)] = max(velocities.get((role, step), 0), velocity)
        max_step = max(max_step, step)
    bars = max(1, min(4, -(-(max_step + 1) // per_bar)))  # ceil, capped at 4 bars
    while per_bar * bars > MAX_STEPS and bars > 1:
        bars -= 1
    total = per_bar * bars
    dropped = 0
    clean: dict[str, list] = {}
    levels: dict = {}
    for role, steps in hits.items():
        kept = sorted(s for s in steps if 0 <= s < total)
        dropped += len(steps) - len(kept)
        if not kept:
            continue
        clean[role] = kept
        role_levels = {}
        for s in kept:  # dynamics from velocity: quiet -> ghost, loud -> accent
            velocity = velocities.get((role, s), 90)
            if velocity < _GHOST_BELOW:
                role_levels[s] = LEVEL_GHOST
            elif velocity > _ACCENT_ABOVE:
                role_levels[s] = LEVEL_ACCENT
        if role_levels:
            levels[role] = role_levels
    if dropped:
        info["dropped"] = dropped
    if not clean:
        raise ValueError("no notes landed inside the importable range")
    return Pattern("MIDI import", total, grid, clean, beats, unit, bars, levels), info
