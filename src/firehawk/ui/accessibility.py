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
        """Forces the accessible name; everything else falls back to native."""

        def __init__(self, name: str):
            super().__init__()
            self._name = name

        def GetName(self, childId):  # noqa: N802 - wx API name
            return (wx.ACC_OK, self._name)


def set_accessible_name(control: wx.Window, name: str) -> None:
    """Give *control* a stable accessible name for screen readers."""
    control.SetName(name)
    if _HAS_ACC:
        acc = _NamedAccessible(name)
        control.SetAccessible(acc)
        # Keep a Python reference alive so the accessible isn't garbage-collected.
        control._firehawk_acc = acc  # type: ignore[attr-defined]
