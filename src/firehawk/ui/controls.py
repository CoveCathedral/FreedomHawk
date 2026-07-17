"""Accessible parameter controls.

Every parameter is built from one of three control types that NVDA announces
reliably (verified with the user's screen reader):

* **checkbox** for booleans (name carried in its label);
* **slider** for continuous values and wide integer ranges (name forced via a
  ``wx.Accessible``; the value is spoken as the slider moves);
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
    """A single parameter's label + widget, wired to a change callback."""

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
        self.control = self._build(parent, value)
        if isinstance(self.control, wx.CheckBox):
            self.label = wx.StaticText(parent, label="")
        else:
            self.label = wx.StaticText(parent, label=self.label_text + ":")
            set_accessible_name(self.control, self.label_text)

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
        cb.Bind(wx.EVT_CHECKBOX, lambda e: self.on_change(self.spec.symbolic_id, e.IsChecked()))
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
            choice = wx.Choice(parent, choices=self._int_option_labels(lo, hi))
            choice.SetSelection(max(0, min(hi - lo, cur - lo)))
            choice.Bind(
                wx.EVT_CHOICE,
                lambda e: self.on_change(self.spec.symbolic_id, self._int_lo + e.GetSelection()),
            )
            self._kind = "choice_int"
            self._int_lo = lo
            return choice
        slider = wx.Slider(parent, value=cur, minValue=lo, maxValue=hi, style=wx.SL_HORIZONTAL)
        self._set_slider_steps(slider, hi - lo)
        slider.Bind(wx.EVT_SLIDER, lambda e: self.on_change(self.spec.symbolic_id, e.GetInt()))
        self._kind = "slider_int"
        return slider

    def _int_option_labels(self, lo: int, hi: int) -> list[str]:
        """Option labels for an integer/enum dropdown.

        Uses the parameter's named options where known; otherwise the numbers.
        """
        options = self.spec.options
        labels = []
        for i, v in enumerate(range(lo, hi + 1)):
            labels.append(options[i] if i < len(options) else str(v))
        return labels

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
        slider.Bind(
            wx.EVT_SLIDER,
            lambda e: self.on_change(self.spec.symbolic_id, self._from_slider(e.GetInt())),
        )
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

    # -- value access ---------------------------------------------------------

    def set_value(self, value) -> None:
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
