"""The Presets browser page.

A scrollable list of presets (factory + the user's saved patches); selecting one shows
a full read-only summary of its signal chain, and Open loads it into the editor so every
parameter becomes editable on the block pages.
"""

from __future__ import annotations

from typing import Callable

import wx

from ..model import ModelCatalog, Preset, PresetEntry, PresetLibrary, summarize_preset
from . import speech
from .accessibility import set_accessible_name


class PresetsPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        library: PresetLibrary,
        catalog: ModelCatalog,
        on_open: Callable[[Preset], None],
        get_current: Callable[[], Preset],
        status: Callable[[str], None] | None = None,
    ):
        super().__init__(parent)
        self.library = library
        self.catalog = catalog
        self.on_open = on_open
        self.get_current = get_current
        self._status = status
        self._entries: list[PresetEntry] = []

        outer = wx.BoxSizer(wx.HORIZONTAL)

        # Left: the preset list.
        left = wx.BoxSizer(wx.VERTICAL)
        list_label = wx.StaticText(self, label="Presets:")
        self.list = wx.ListBox(self, style=wx.LB_SINGLE)
        # Plain SetName only: a forced wx.Accessible would sit in front of the list's
        # native item announcements, so let NVDA read the item text itself.
        self.list.SetName("Presets")
        self.list.Bind(wx.EVT_LISTBOX, self._on_select)
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._open_selected())
        left.Add(list_label, 0, wx.ALL, 4)
        left.Add(self.list, 1, wx.EXPAND | wx.ALL, 4)
        outer.Add(left, 1, wx.EXPAND)

        # Right: details + actions.
        right = wx.BoxSizer(wx.VERTICAL)
        details_label = wx.StaticText(self, label="Details:")
        self.details = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        set_accessible_name(self.details, "Preset details")
        right.Add(details_label, 0, wx.ALL, 4)
        right.Add(self.details, 1, wx.EXPAND | wx.ALL, 4)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.open_btn = wx.Button(self, label="&Open in Editor")
        self.saveas_btn = wx.Button(self, label="&Save Current As...")
        self.delete_btn = wx.Button(self, label="&Delete")
        self.refresh_btn = wx.Button(self, label="&Refresh List")
        for b in (self.open_btn, self.saveas_btn, self.delete_btn, self.refresh_btn):
            buttons.Add(b, 0, wx.ALL, 4)
        self.open_btn.Bind(wx.EVT_BUTTON, lambda e: self._open_selected())
        self.saveas_btn.Bind(wx.EVT_BUTTON, self._on_save_as)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.reload())
        right.Add(buttons, 0, wx.ALL, 4)
        outer.Add(right, 2, wx.EXPAND)

        self.SetSizer(outer)
        self.reload()

    # -- data -----------------------------------------------------------------

    def reload(self) -> None:
        sel_name = None
        if 0 <= self.list.GetSelection() < len(self._entries):
            sel_name = self._entries[self.list.GetSelection()].display
        self._entries = self.library.all_presets()
        self.list.Set([e.display for e in self._entries])
        # Restore selection where possible, else select the first item.
        index = 0
        if sel_name:
            for i, e in enumerate(self._entries):
                if e.display == sel_name:
                    index = i
                    break
        if self._entries:
            self.list.SetSelection(index)
            self._show_details(index)

    def _show_details(self, index: int) -> None:
        if 0 <= index < len(self._entries):
            entry = self._entries[index]
            self.details.SetValue(summarize_preset(entry.preset, self.catalog))
            self.delete_btn.Enable(entry.deletable)

    # -- events ---------------------------------------------------------------

    def _on_select(self, event: wx.CommandEvent) -> None:
        self._show_details(self.list.GetSelection())

    def _open_selected(self) -> None:
        index = self.list.GetSelection()
        if 0 <= index < len(self._entries):
            entry = self._entries[index]
            self.on_open(entry.preset.copy())
            self._announce(f"Opened preset {entry.name}")

    def _on_save_as(self, event: wx.CommandEvent) -> None:
        current = self.get_current()
        default_name = current.meta.get("name", "My Preset")
        with wx.TextEntryDialog(self, "Save current tone as:", "Save Preset", default_name) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.GetValue().strip()
        if not name:
            return
        self.library.save(current, name)
        self.reload()
        self._announce(f"Saved preset {name}")

    def _on_delete(self, event: wx.CommandEvent) -> None:
        index = self.list.GetSelection()
        if not (0 <= index < len(self._entries)):
            return
        entry = self._entries[index]
        if not entry.deletable:
            wx.MessageBox("Factory presets cannot be deleted.", "Delete", wx.ICON_INFORMATION)
            return
        if wx.MessageBox(
            f"Delete user preset '{entry.name}'?", "Delete preset",
            wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.library.delete(entry)
        self.reload()
        self._announce(f"Deleted preset {entry.name}")

    def _announce(self, message: str) -> None:
        # Speak it too: Open/Save As/Delete results (especially Save As, which otherwise
        # gives no feedback at all) are inaudible if only shown in the status bar.
        speech.speak(message)
        if self._status is not None:
            self._status(message)
