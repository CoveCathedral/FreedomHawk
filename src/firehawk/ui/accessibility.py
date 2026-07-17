"""Reliable accessible names for wx controls.

`SetName` alone proved unreliable for sliders/spins with NVDA (some read as
"slider 59" with no name).  The dependable way on Windows is to attach a
``wx.Accessible`` that returns the name explicitly while deferring every other
property (role, value, state) to the standard implementation, so the slider still
announces its value and role — only the name is forced.
"""

from __future__ import annotations

import wx

_HAS_ACC = hasattr(wx, "Accessible")


if _HAS_ACC:

    class _NamedAccessible(wx.Accessible):
        """Forces the accessible name (and optionally value); rest falls back to native."""

        def __init__(self, name: str, value_fn=None):
            super().__init__()
            self._name = name
            self._value_fn = value_fn

        def GetName(self, childId):  # noqa: N802 - wx API name
            # childId 0 is the control itself; children (list items, dropdown
            # options) must keep their own native names, so defer for those.
            if childId == 0:
                return (wx.ACC_OK, self._name)
            return (wx.ACC_NOT_IMPLEMENTED, "")

        def GetValue(self, childId):  # noqa: N802 - wx API name
            if childId == 0 and self._value_fn is not None:
                try:
                    return (wx.ACC_OK, str(self._value_fn()))
                except Exception:  # noqa: BLE001
                    pass
            return (wx.ACC_NOT_IMPLEMENTED, "")


def set_accessible_name(control: wx.Window, name: str, value_fn=None) -> None:
    """Give *control* a stable accessible name (and optional spoken value) for readers.

    *value_fn*, if given, is called to produce the value a screen reader announces —
    used to speak a slider's real, formatted value (e.g. "-54.5 dB") instead of its
    raw position.
    """
    control.SetName(name)
    if _HAS_ACC:
        acc = _NamedAccessible(name, value_fn)
        control.SetAccessible(acc)
        # Keep a Python reference alive so the accessible isn't garbage-collected.
        control._firehawk_acc = acc  # type: ignore[attr-defined]
