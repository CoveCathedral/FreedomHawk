"""Visual theming: a high-contrast dark mode with large white labels.

Designed for low-vision use — dark background, large bold white text labels, and
readable input fields.  Applied recursively so it also covers controls created later
when a block's parameters are rebuilt.

On Windows we additionally ask the platform to render native controls (checkboxes,
combos, spin buttons, scrollbars) in dark mode where the wx build supports it; the
manual colouring below covers everything else and is the fallback when it doesn't.
"""

from __future__ import annotations

import wx

# Palette
DARK_BG = wx.Colour(0x1E, 0x1E, 0x1E)      # window / panel background
DARK_INPUT = wx.Colour(0x2D, 0x2D, 0x30)   # text fields, lists, combos
LIGHT_FG = wx.Colour(0xFF, 0xFF, 0xFF)      # text
MUTED_FG = wx.Colour(0xE0, 0xE0, 0xE0)

LIGHT_BG = wx.NullColour  # let the system decide in light mode

LABEL_POINT_SIZE = 12
SIDEBAR_POINT_SIZE = 15   # the tab list is navigation — larger, for low-vision reading


def label_font() -> wx.Font:
    return wx.Font(wx.FontInfo(LABEL_POINT_SIZE).Bold())


def input_font() -> wx.Font:
    return wx.Font(wx.FontInfo(LABEL_POINT_SIZE))


def sidebar_font() -> wx.Font:
    return wx.Font(wx.FontInfo(SIDEBAR_POINT_SIZE).Bold())


def enlarge_listbook_sidebar(listbook) -> None:
    """Give a Listbook's tab list the larger font and widen it to fit — low-vision reading.

    A Listbook sizes its list to the (small) default font at creation and won't re-widen on
    its own, so measure the widest tab label at the larger font and force the width.  Shared
    by the FreedomHawk window and the standalone Sequin window.
    """
    getter = getattr(listbook, "GetListView", None)
    lv = getter() if callable(getter) else None
    if lv is None:
        children = listbook.GetChildren()
        lv = children[0] if children else None
    if lv is None:
        return
    font = sidebar_font()
    lv.SetFont(font)
    dc = wx.ClientDC(lv)
    dc.SetFont(font)
    widest = 0
    for i in range(lv.GetItemCount()):
        widest = max(widest, dc.GetTextExtent(lv.GetItemText(i)).width)
    width = (widest or 120) + 64
    try:
        lv.SetColumnWidth(0, width)
    except Exception:  # noqa: BLE001 - not every build exposes a report column
        pass
    lv.SetMinSize(wx.Size(width, -1))
    listbook.SendSizeEvent()


def enable_native_dark_mode(app: wx.App) -> None:
    """Ask Windows to draw native controls dark, where the wx build supports it."""
    for attr in ("MSWEnableDarkMode",):
        fn = getattr(app, attr, None)
        if callable(fn):
            try:
                fn()  # some builds accept a flags argument; default is fine
            except TypeError:
                try:
                    fn(0)
                except Exception:
                    pass
            except Exception:
                pass


def apply(root: wx.Window, dark: bool = True) -> None:
    """Recursively theme *root* and all descendants."""
    stack = [root]
    while stack:
        win = stack.pop()
        _style(win, dark)
        stack.extend(win.GetChildren())
    root.Refresh()


def _style(win: wx.Window, dark: bool) -> None:
    if not dark:
        # Reset to system defaults for light mode.
        win.SetBackgroundColour(wx.NullColour)
        win.SetForegroundColour(wx.NullColour)
        if isinstance(win, wx.StaticText):
            win.SetFont(label_font())  # keep labels large even in light mode
        elif isinstance(win, wx.ListCtrl):
            win.SetFont(sidebar_font())  # keep the tab sidebar large in light mode too
        return

    if isinstance(win, wx.ListCtrl):  # the Listbook's tab sidebar (before generic panels)
        win.SetBackgroundColour(DARK_INPUT)
        win.SetForegroundColour(LIGHT_FG)
        win.SetFont(sidebar_font())
    elif isinstance(win, wx.StaticText):
        win.SetForegroundColour(LIGHT_FG)
        win.SetBackgroundColour(DARK_BG)
        win.SetFont(label_font())
    elif isinstance(win, (wx.TextCtrl, wx.ListBox)):
        win.SetBackgroundColour(DARK_INPUT)
        win.SetForegroundColour(LIGHT_FG)
        win.SetFont(input_font())
    elif isinstance(win, wx.CheckBox):
        win.SetForegroundColour(LIGHT_FG)
        win.SetBackgroundColour(DARK_BG)
        win.SetFont(label_font())
    elif isinstance(win, (wx.Choice, wx.ComboBox, wx.SpinCtrl, wx.SpinCtrlDouble, wx.Button)):
        win.SetBackgroundColour(DARK_INPUT)
        win.SetForegroundColour(LIGHT_FG)
    elif isinstance(win, wx.Slider):
        win.SetBackgroundColour(DARK_BG)
        win.SetForegroundColour(LIGHT_FG)
    else:
        # Panels, scrolled windows, listbook, the frame itself.
        win.SetBackgroundColour(DARK_BG)
        win.SetForegroundColour(LIGHT_FG)
