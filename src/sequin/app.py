"""Sequin — the accessible step sequencer, as a standalone app.

Runs the same Sequin that FreedomHawk embeds — the accessible drum machine / step
sequencer (``ui.drumspanel.DrumsPanel`` over the pedal-independent ``practice`` engine) —
in its own window, with its own menu.  This is the *tandem standalone* entry point: launch
it with ``Sequin.bat`` or ``python -m sequin``.

Sequin is its own package (``sequin``); FreedomHawk embeds it and depends on it, so a
change here reaches both.  Launch standalone with ``Sequin.bat`` or ``python -m sequin``.
"""
from __future__ import annotations

import os
from pathlib import Path

import wx

from .config import AppSettings
from .ui import speech, theme
from .ui.drumspanel import DrumsPanel
from .ui.metronomepanel import MetronomePanel

APP_TITLE = "Sequin — Accessible Step Sequencer"


class SequinFrame(wx.Frame):
    """A standalone window hosting Sequin (the sequencer) and a metronome, in tabs."""

    def __init__(self, dark: bool = True):
        super().__init__(None, title=APP_TITLE, size=(1000, 720))
        self.settings = AppSettings()
        self.dark_mode = dark
        self.status = self.CreateStatusBar()
        self.status.SetStatusText(
            "Sequin — pick a groove and press Start, or Ctrl+D to edit a pattern.")

        # Two tabs down the left, like FreedomHawk: the sequencer and a metronome.
        self.listbook = wx.Listbook(self, style=wx.LB_LEFT)
        self.drums = DrumsPanel(self.listbook, settings=self.settings,
                                status=self.status.SetStatusText)
        self.metronome = MetronomePanel(self.listbook, status=self.status.SetStatusText)
        self.listbook.AddPage(self.drums, "Sequin")
        self.listbook.AddPage(self.metronome, "Metronome")
        self.listbook.SetSelection(0)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.listbook, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self._build_menu()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        # F5 plays/stops the current tab from anywhere in the window (see the main app).
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        theme.apply(self, self.dark_mode)
        theme.enlarge_listbook_sidebar(self.listbook)
        self.Centre()
        wx.CallAfter(lambda: theme.enlarge_listbook_sidebar(self.listbook))

    # -- menu -----------------------------------------------------------------

    def _build_menu(self) -> None:
        mb = wx.MenuBar()

        tools = wx.Menu()
        transport = tools.Append(wx.ID_ANY, "&Play or Stop This Tab\tF5")
        tools.AppendSeparator()
        editor = tools.Append(wx.ID_ANY, "&Pattern Editor...\tCtrl+D")
        library = tools.Append(wx.ID_ANY, "Pattern &Library...")
        song = tools.Append(wx.ID_ANY, "Song &Builder...")
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
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_current_transport(), transport)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.open_editor(blank=True), editor)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.open_library(), library)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.open_song_builder(), song)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.export_wav(), wav)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.export_pattern_file(), pat_ex)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.import_pattern_file(), pat_im)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.export_midi(), midi_ex)
        self.Bind(wx.EVT_MENU, lambda e: self.drums.import_midi(), midi_im)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), quit_item)
        self.Bind(wx.EVT_MENU, self._on_dark, self.dark_item)
        self.Bind(wx.EVT_MENU, self._on_manual, manual)
        self.Bind(wx.EVT_MENU, self._on_about, about)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_F5:
            self._toggle_current_transport()
            return
        event.Skip()

    def _toggle_current_transport(self) -> None:
        """Start/stop the current tab's loop (F5), wherever focus is. Both tabs (Sequin,
        Metronome) have a transport and speak their own state."""
        page = self.listbook.GetCurrentPage()
        toggle = getattr(page, "toggle_transport", None)
        if callable(toggle):
            toggle()
        else:
            speech.speak("This tab has no Start control.")

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
        self.metronome.dispose()
        self.Destroy()


def main() -> None:
    app = wx.App(False)
    theme.enable_native_dark_mode(app)
    SequinFrame().Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
