"""Accessible parameter controls.

Every parameter is built from one of three control types that NVDA announces
reliably (verified with the user's screen reader):

* **checkbox** for booleans (name carried in its label);
* **slider** for continuous values and wide integer ranges (name forced via a
  ``wx.Accessible``; its real, formatted value is both shown as text and offered to
  the screen reader as the spoken value);
* **dropdown** (``wx.Choice``) for small integer/enumerated ranges (name forced,
  selected option spoken; also the natural home for named choices later).

Spin controls are deliberately avoided: they are composite native widgets whose
inner edit field does not expose the accessible name, so they read only their value.
"""

from __future__ import annotations

from typing import Callable

import wx

from ..model import ParamSpec, ValueType
from .accessibility import set_accessible_name

# Parameters whose real-world range carries a unit we can announce.
_UNIT_HINTS = {
    "Thresh": "dB",
    "Thresh/G": "dB",
    "@tempo": "BPM",
}

# Integer ranges up to this span use a dropdown; wider ranges use a slider.
_MAX_CHOICE_SPAN = 32


def _unit_for(spec: ParamSpec) -> str:
    return _UNIT_HINTS.get(spec.symbolic_id, "")


def accessible_label(spec: ParamSpec) -> str:
    unit = _unit_for(spec)
    return f"{spec.display_name} ({unit})" if unit else spec.display_name


class ParamControl:
    """A single parameter's label, widget, and live value readout."""

    def __init__(
        self,
        parent: wx.Window,
        spec: ParamSpec,
        value,
        on_change: Callable[[str, object], None],
    ):
        self.spec = spec
        self.on_change = on_change
        self.label_text = accessible_label(spec)
        self._kind = ""
        self._mode = ""          # continuous mapping mode: pct01 | direct | scaled
        self._lo = 0.0
        self._hi = 1.0
        self._smin = 0
        self._smax = 100
        self._int_lo = 0
        self._current = value if value is not None else spec.default

        self.control = self._build(parent, value)
        if isinstance(self.control, wx.CheckBox):
            self.label = wx.StaticText(parent, label="")
        else:
            # Sliders show their live value in the label ("Bass: 59%") and offer the
            # same formatted value to the screen reader as the spoken value.
            self.label = wx.StaticText(parent, label=self._label_display())
            value_fn = self.format_value_current if self._is_slider else None
            set_accessible_name(self.control, self.label_text, value_fn)

    def _label_display(self) -> str:
        if self._is_slider:
            return f"{self.label_text}: {self.format_value(self._current)}"
        return f"{self.label_text}:"

    @property
    def _is_slider(self) -> bool:
        return self._kind in ("slider_cont", "slider_int")

    # -- construction ---------------------------------------------------------

    def _build(self, parent: wx.Window, value) -> wx.Window:
        vt = self.spec.value_type
        if vt is ValueType.BOOL:
            return self._build_bool(parent, value)
        if vt is ValueType.INT:
            return self._build_int(parent, value)
        if vt is ValueType.STRING:
            return self._build_string(parent, value)
        return self._build_continuous(parent, value)

    def _build_bool(self, parent, value) -> wx.CheckBox:
        cb = wx.CheckBox(parent, label=self.label_text)  # label = accessible name
        cb.SetValue(bool(value))
        cb.Bind(wx.EVT_CHECKBOX, lambda e: self._emit(e.IsChecked()))
        self._kind = "bool"
        return cb

    def _build_string(self, parent, value) -> wx.TextCtrl:
        tc = wx.TextCtrl(parent, value="" if value is None else str(value), style=wx.TE_READONLY)
        self._kind = "string"
        return tc

    def _build_int(self, parent, value) -> wx.Window:
        lo, hi = int(self.spec.minimum), int(self.spec.maximum)
        cur = int(value if value is not None else self.spec.default)
        if hi - lo <= _MAX_CHOICE_SPAN:
            self._int_lo = lo
            choice = wx.Choice(parent, choices=self._int_option_labels(lo, hi))
            choice.SetSelection(max(0, min(hi - lo, cur - lo)))
            choice.Bind(wx.EVT_CHOICE, lambda e: self._emit(self._int_lo + e.GetSelection()))
            self._kind = "choice_int"
            return choice
        slider = wx.Slider(parent, value=cur, minValue=lo, maxValue=hi, style=wx.SL_HORIZONTAL)
        self._set_slider_steps(slider, hi - lo)
        slider.Bind(wx.EVT_SLIDER, lambda e: self._emit(e.GetInt()))
        self._kind = "slider_int"
        return slider

    def _int_option_labels(self, lo: int, hi: int) -> list[str]:
        options = self.spec.options
        return [options[i] if i < len(options) else str(v) for i, v in enumerate(range(lo, hi + 1))]

    def _build_continuous(self, parent, value) -> wx.Slider:
        lo, hi = float(self.spec.minimum), float(self.spec.maximum)
        val = float(value if value is not None else self.spec.default)
        self._lo, self._hi = lo, hi
        if lo == 0.0 and hi == 1.0:
            self._mode, self._smin, self._smax = "pct01", 0, 100
        elif (hi - lo) >= 4:
            self._mode, self._smin, self._smax = "direct", round(lo), round(hi)
        else:
            self._mode, self._smin, self._smax = "scaled", 0, 100
        slider = wx.Slider(
            parent, value=self._to_slider(val),
            minValue=self._smin, maxValue=self._smax, style=wx.SL_HORIZONTAL,
        )
        self._set_slider_steps(slider, self._smax - self._smin)
        slider.Bind(wx.EVT_SLIDER, lambda e: self._emit(self._from_slider(e.GetInt())))
        self._kind = "slider_cont"
        return slider

    @staticmethod
    def _set_slider_steps(slider: wx.Slider, span: int) -> None:
        slider.SetLineSize(1)
        slider.SetPageSize(max(1, span // 10))

    # -- continuous value mapping ---------------------------------------------

    def _to_slider(self, val: float) -> int:
        if self._mode == "pct01":
            return int(round(val * 100))
        if self._mode == "direct":
            return int(round(val))
        frac = 0.0 if self._hi == self._lo else (val - self._lo) / (self._hi - self._lo)
        return int(round(self._smin + frac * (self._smax - self._smin)))

    def _from_slider(self, pos: int) -> float:
        if self._mode == "pct01":
            return pos / 100.0
        if self._mode == "direct":
            return float(pos)
        frac = (pos - self._smin) / (self._smax - self._smin) if self._smax != self._smin else 0.0
        return self._lo + frac * (self._hi - self._lo)

    # -- value display / change -----------------------------------------------

    def format_value(self, val) -> str:
        """A readable string for the current value (with units where known)."""
        k = self._kind
        if k == "bool":
            return "on" if val else "off"
        if k == "string":
            return "" if val is None else str(val)
        if k == "choice_int":
            i = int(val) - self._int_lo
            opts = self.spec.options
            return opts[i] if 0 <= i < len(opts) else str(int(val))
        if k == "slider_int":
            return str(int(val))
        unit = _unit_for(self.spec)
        if self._mode == "pct01":
            return f"{round(float(val) * 100)}%"
        if unit:
            return f"{float(val):.1f} {unit}"
        if self._mode == "direct":
            return f"{float(val):.0f}"
        return f"{float(val):.2f}"

    def format_value_current(self) -> str:
        return self.format_value(self._current)

    def _emit(self, value) -> None:
        self._current = value
        self._refresh_readout()
        self.on_change(self.spec.symbolic_id, value)

    def _refresh_readout(self) -> None:
        if self._is_slider:
            self.label.SetLabel(self._label_display())

    def set_value(self, value) -> None:
        self._current = value
        if self._kind == "bool":
            self.control.SetValue(bool(value))
        elif self._kind == "string":
            self.control.SetValue("" if value is None else str(value))
        elif self._kind == "choice_int":
            self.control.SetSelection(int(value) - self._int_lo)
        elif self._kind == "slider_int":
            self.control.SetValue(int(value))
        elif self._kind == "slider_cont":
            self.control.SetValue(self._to_slider(float(value)))
        self._refresh_readout()
