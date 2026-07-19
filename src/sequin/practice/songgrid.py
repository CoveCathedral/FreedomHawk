"""A flattened, navigable view of a whole song for the song-wide beat editor.

The Song Builder arranges *sections*, each a pattern played a number of times (``repeats``,
which may be a half).  The song-wide beat editor needs to walk one continuous timeline
across every section, repeat, bar and step — even though sections can differ in meter,
tempo and length — and map any point back to the exact step of the exact section's pattern
so an edit lands in the right place.

``SongGrid`` is that map.  It is deliberately UI-free and pure-data (no wx, no audio) so it
can be unit-tested and lifts cleanly into the standalone Sequin project.  Positions are
plain integers: a linear step index from 0 to ``total_steps - 1``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GridPos:
    """Everything about one point on the song timeline."""
    section: int          # index into the song's sections
    name: str             # the section's display name
    repeat: int           # 0-based repeat of that section
    repeats: float        # how many times the section plays in all
    bar: int              # 0-based bar within the repeat
    beat: int             # 0-based beat within the bar
    step_in_beat: int     # 0-based grid step within the beat
    step_in_pattern: int  # 0-based step within the section's pattern (what an edit targets)
    per_bar: int          # grid steps in one bar of this section
    steps_per_beat: int   # grid steps in one beat of this section
    meter: str            # e.g. "4/4"


class SongGrid:
    """A linear step timeline over a song's sections.

    Build it from ``entries`` — a list of ``(pattern, repeats, name)`` tuples (the patterns
    are the editable base patterns; tempo/kit/feel don't affect the grid).  Each section
    contributes ``round(pattern.steps * repeats)`` steps, so a half repeat is the pattern's
    first half.  All navigation clamps to ``[0, total_steps - 1]``.
    """

    def __init__(self, entries: list) -> None:
        self._patterns = []
        self._names = []
        self._reps = []
        self._section_steps = []
        self._starts = []
        cursor = 0
        for pattern, repeats, name in entries:
            reps = max(0.5, round(float(repeats) * 2) / 2)
            steps = max(1, int(round(pattern.steps * reps)))
            self._patterns.append(pattern)
            self._names.append(name)
            self._reps.append(reps)
            self._section_steps.append(steps)
            self._starts.append(cursor)
            cursor += steps
        self.total_steps = max(1, cursor)

    # -- lookups --------------------------------------------------------------

    @property
    def sections(self) -> int:
        return len(self._patterns)

    def section_of(self, pos: int) -> int:
        """The section index a linear position falls in."""
        pos = self._clamp(pos)
        lo, hi = 0, len(self._starts) - 1
        while lo < hi:                       # binary search on the section starts
            mid = (lo + hi + 1) // 2
            if self._starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def pattern_at(self, pos: int):
        """The section pattern a position edits."""
        return self._patterns[self.section_of(pos)]

    def section_start(self, index: int) -> int:
        """The linear position where a section begins."""
        return self._starts[max(0, min(len(self._starts) - 1, index))]

    def locate(self, pos: int) -> GridPos:
        """Resolve a linear position to its full :class:`GridPos`."""
        pos = self._clamp(pos)
        i = self.section_of(pos)
        p = self._patterns[i]
        local = pos - self._starts[i]
        per_bar = max(1, p.steps // max(1, p.bars))
        spb = max(1, p.steps_per_beat)
        step_in_pattern = local % p.steps
        repeat = local // p.steps
        bar = step_in_pattern // per_bar
        in_bar = step_in_pattern % per_bar
        return GridPos(
            section=i, name=self._names[i], repeat=repeat, repeats=self._reps[i],
            bar=bar, beat=in_bar // spb, step_in_beat=in_bar % spb,
            step_in_pattern=step_in_pattern, per_bar=per_bar, steps_per_beat=spb,
            meter=p.meter_label())

    def describe(self, pos: int) -> str:
        """A spoken location, e.g. ``"Section 2, Chorus, repeat 2, bar 1, beat 3"``.

        The section ordinal leads so two same-named sections (a song with two Verses and
        two Choruses) are never confused — the name alone would read identically."""
        g = self.locate(pos)
        head = f"Section {g.section + 1}"
        if g.name:
            head += f", {g.name}"
        parts = [head]
        if g.repeats != 1:
            parts.append(f"repeat {g.repeat + 1}")
        parts.append(f"bar {g.bar + 1}")
        parts.append(f"beat {g.beat + 1}")
        if g.step_in_beat:
            parts.append(f"step {g.step_in_beat + 1}")
        return ", ".join(parts)

    # -- movement -------------------------------------------------------------

    def _clamp(self, pos: int) -> int:
        return max(0, min(self.total_steps - 1, int(pos)))

    def _section_bounds(self, pos: int) -> tuple[int, int]:
        i = self.section_of(pos)
        start = self._starts[i]
        return start, start + self._section_steps[i] - 1

    def step(self, pos: int, direction: int) -> int:
        """One grid step (the smallest move), across section boundaries."""
        return self._clamp(pos + (1 if direction >= 0 else -1))

    def beat(self, pos: int, direction: int) -> int:
        """One beat, staying within the current section (clamped at its ends)."""
        g = self.locate(pos)
        lo, hi = self._section_bounds(pos)
        return max(lo, min(hi, pos + (g.steps_per_beat if direction >= 0
                                      else -g.steps_per_beat)))

    def bar(self, pos: int, direction: int) -> int:
        """One bar, staying within the current section (clamped at its ends)."""
        g = self.locate(pos)
        lo, hi = self._section_bounds(pos)
        return max(lo, min(hi, pos + (g.per_bar if direction >= 0 else -g.per_bar)))

    def section(self, pos: int, direction: int) -> int:
        """Jump to the next section's start (forward), or to the current section's start
        — then the previous section's start — going back (a two-stage Home, like a media
        'previous track')."""
        i = self.section_of(pos)
        if direction >= 0:
            if i + 1 < len(self._starts):
                return self._starts[i + 1]
            return self._section_bounds(pos)[1]        # last section: go to its end
        if pos > self._starts[i]:
            return self._starts[i]                     # to the start of this section
        return self._starts[max(0, i - 1)]             # already there: previous section

    def home(self) -> int:
        return 0

    def end(self) -> int:
        return self.total_steps - 1
