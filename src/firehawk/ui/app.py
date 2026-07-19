"""wxPython application entry point."""

from __future__ import annotations

import wx

from sequin.ui import theme
from .mainframe import MainFrame


class FirehawkApp(wx.App):
    def OnInit(self) -> bool:
        theme.enable_native_dark_mode(self)
        frame = MainFrame()
        frame.Show()
        self.SetTopWindow(frame)
        return True


def run() -> int:
    app = FirehawkApp()
    app.MainLoop()
    return 0
