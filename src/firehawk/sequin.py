"""Sequin — the accessible step sequencer, as a standalone app.

Runs the same Sequin that FreedomHawk embeds — the accessible drum machine / step
sequencer (``ui.drumspanel.DrumsPanel`` over the pedal-independent ``practice`` engine) —
in its own window, with its own menu.  This is the *tandem standalone* entry point: launch
it with ``Sequin.bat`` or ``python -m firehawk.sequin``.

It shares FreedomHawk's code for now; the eventual separate repo lifts ``practice`` plus the
Sequin UI out wholesale (they only touch the rest of the app through settings/theme/speech).
"""
from __future__ import annotations

import os
from pathlib import Path

import wx

from .config import AppSettings
from .ui import theme
from .ui.drumspanel import DrumsPanel

APP_TITLE = "Sequin — Accessible Step Sequencer"


class SequinFrame(wx.Frame):
    """A standalone window hosting Sequin (the sequencer) and its tools."""

    def __init__(self, dark: bool = True):
        super().__init__(None, title=APP_TITLE, size=(1000, 720))
        self.settings = AppSettings()
        self.dark_mode = dark
        self.status = self.CreateStatusBar()
        self.status.SetStatusText(
            "Sequin — pick a groove and press Start, or Ctrl+D to edit a pattern.")

        self.drums = DrumsPanel(self, settings=self.settings, status=self.status.SetStatusText)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.drums, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self._build_menu()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        theme.apply(self, self.dark_mode)
        self.Centre()

    # -- menu -----------------------------------------------------------------

    def _build_menu(self) -> None:
        mb = wx.MenuBar()

        tools = wx.Menu()
        editor = tools.Append(wx.ID_ANY, "&Pattern Editor...\tCtrl+D")
        library = tools.Append(wx.ID_ANY, "Pattern &Library...")
        tools.AppendSeparator()
        wav = tools.Append(wx.ID_ANY, "Export Loop as &WAV...")
        pat_ex = tools.Append(wx.ID_ANY, "&Export Pattern...")
        pat_im = tools.Append(wx.ID_ANY, "&Import Pattern...")
        midi_ex = tools.Append(wx.ID_ANY, "Export as &MIDI...")
        midi_im = tools.Append(wx.ID_ANY, "Import MIDI &File...")
        tools.AppendSeparator()
        quit_item = tools.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        mb.Append(tools, "&Tools")

        settings_menu = wx.Menu()
        self.dark_item = settings_menu.AppendCheckItem(wx.ID_ANY, "&Dark Mode")
        self.dark_item.Check(self.dark_mode)
        mb.Append(settings_menu, "&Settings")

        help_menu = wx.Menu()
        manual = help_menu.Append(wx.ID_ANY, "&User Manual...")
        about = help_menu.Append(wx.ID_ABOUT, "&About Sequin")
        mb.Append(help_menu, "&Help")

        self.SetMenuBar(mb)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.open_editor(blank=True), editor)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.open_library(), library)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.export_wav(), wav)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.export_pattern_file(), pat_ex)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.import_pattern_file(), pat_im)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.export_midi(), midi_ex)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.import_midi(), midi_im)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), quit_item)
        self.Bind(wx.EVT_MENU, self._on_dark, self.dark_item)
        self.Bind(wx.EVT_MENU, self._on_manual, manual)
        self.Bind(wx.EVT_MENU, self._on_about, about)

    def _on_dark(self, event) -> None:
        self.dark_mode = self.dark_item.IsChecked()
        theme.apply(self, self.dark_mode)
        self.Refresh()

    def _on_manual(self, event) -> None:
        docs = Path.cwd() / "docs"
        for name in ("user-manual.html", "user-manual.md"):
            manual = docs / name
            if manual.is_file():
                try:
                    os.startfile(str(manual))  # noqa: S606 - our own doc file
                    return
                except OSError:
                    continue
        wx.MessageBox("The manual is in docs/user-manual.html, and online at "
                      "github.com/CoveCathedral/FreedomHawk.", "User manual",
                      wx.ICON_INFORMATION)

    def _on_about(self, event) -> None:
        wx.MessageBox(
            "Sequin — the accessible step sequencer\n\n"
            "A screen-reader-first, keyboard-only drum machine and step sequencer for "
            "blind and low-vision musicians (built and tested with NVDA). Designed "
            "non-visually from the ground up — the spoken tracker grid is the interface.\n\n"
            "Ships inside FreedomHawk and standalone. MIT.\n"
            "github.com/CoveCathedral/FreedomHawk",
            "About Sequin", wx.ICON_INFORMATION)

    def _on_close(self, event) -> None:
        self.drums.dispose()
        self.Destroy()


def main() -> None:
    app = wx.App(False)
    theme.enable_native_dark_mode(app)
    SequinFrame().Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
