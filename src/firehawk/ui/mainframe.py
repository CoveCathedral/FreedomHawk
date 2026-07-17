"""The main application window.

A :class:`wx.Listbook` presents a Presets browser followed by the signal-chain blocks
(Wah, Compressor, Amp, ...), each a keyboard-navigable page.  The menu bar provides
preset new/open/save, quick "Go" jumps to any page with hotkeys, and settings including
a high-contrast dark mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import wx

from ..model import EditBuffer, ModelCatalog, Preset, PresetLibrary, SLOT_LAYOUT
from ..transport.serialport import find_firehawk_ports, list_serial_ports
from . import theme
from .accessibility import set_accessible_name
from .blockpanel import BlockPanel
from .presetspanel import PresetsPanel

APP_TITLE = "Firehawk Accessible Controller"


def _is_within(window: wx.Window | None, ancestor: wx.Window) -> bool:
    """True if *window* is *ancestor* or a descendant of it."""
    while window is not None:
        if window is ancestor:
            return True
        window = window.GetParent()
    return False


class MainFrame(wx.Frame):
    def __init__(self, catalog: ModelCatalog | None = None, device_id: int | None = None,
                 dark: bool = True):
        super().__init__(None, title=APP_TITLE, size=(900, 680))
        self.catalog = catalog or ModelCatalog()
        self.device_id = device_id
        self.dark_mode = dark
        self.buffer = EditBuffer(self.catalog)
        self.library = PresetLibrary(self.catalog.data_dir)
        self._dirty = False
        self.buffer.add_listener(self._on_buffer_change)

        self.status = self.CreateStatusBar()
        self.status.SetStatusText("Ready — editing offline. Presets load and save locally.")

        self.listbook = wx.Listbook(self, style=wx.LB_LEFT)
        self._view_ids: list[str] = []
        self._build_pages()
        self._build_menu()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.listbook, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.Centre()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._apply_theme()

    # -- unsaved-changes tracking --------------------------------------------

    def _on_buffer_change(self, *_args) -> None:
        self._dirty = True

    def _confirm_discard(self) -> bool:
        """Return True if it's OK to replace the current preset (saved or discarded)."""
        if not self._dirty:
            return True
        result = wx.MessageBox(
            "The current preset has unsaved changes.\n\nSave them before continuing?",
            "Unsaved changes", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
        )
        if result == wx.CANCEL:
            return False
        if result == wx.YES:
            return self._on_save(None)  # True only if actually saved
        return True  # No = discard

    # -- theming --------------------------------------------------------------

    def _themer(self, window: wx.Window) -> None:
        theme.apply(window, self.dark_mode)

    def _apply_theme(self) -> None:
        theme.apply(self, self.dark_mode)
        self.Refresh()

    # -- pages ----------------------------------------------------------------

    def _build_pages(self) -> None:
        self.listbook.DeleteAllPages()
        self._view_ids = []

        presets = PresetsPanel(
            self.listbook, self.library, self.catalog,
            on_open=self._guarded_open,
            get_current=lambda: self.buffer.preset,
            status=self.status.SetStatusText,
        )
        self.listbook.AddPage(presets, "Presets")
        self._view_ids.append("presets")

        for slot in SLOT_LAYOUT:
            page = BlockPanel(
                self.listbook, slot, self.buffer, self.catalog,
                device_id=self.device_id, status=self.status.SetStatusText,
                themer=self._themer,
            )
            self.listbook.AddPage(page, slot.display_name)
            self._view_ids.append(slot.id)

        if self.listbook.GetPageCount():
            self.listbook.SetSelection(0)

    def _refresh_block_pages(self) -> None:
        for i in range(self.listbook.GetPageCount()):
            page = self.listbook.GetPage(i)
            if isinstance(page, BlockPanel):
                page.refresh()

    def _goto(self, index: int) -> None:
        if 0 <= index < self.listbook.GetPageCount():
            self.listbook.SetSelection(index)
            page = self.listbook.GetPage(index)
            wx.CallAfter(self._focus_first, page)

    def _goto_view(self, view_id: str) -> None:
        if view_id in self._view_ids:
            self._goto(self._view_ids.index(view_id))

    @staticmethod
    def _focus_first(page: wx.Window) -> None:
        for child in page.GetChildren():
            if child.IsShownOnScreen() and child.AcceptsFocus():
                child.SetFocus()
                return

    # -- keyboard -------------------------------------------------------------

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        # Escape walks back: from a page's controls to the block list, then to Presets.
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            if self._escape_back():
                return
        event.Skip()

    def _list_view(self) -> wx.Window | None:
        getter = getattr(self.listbook, "GetListView", None)
        if callable(getter):
            return getter()
        children = self.listbook.GetChildren()
        return children[0] if children else None

    def _escape_back(self) -> bool:
        """Two-level 'back': content -> block list -> Presets.  Returns True if handled."""
        listview = self._list_view()
        focus = wx.Window.FindFocus()
        on_list = listview is not None and _is_within(focus, listview)
        if not on_list:
            # Focus is inside a page's content: return to the navigation list.
            if listview is not None:
                listview.SetFocus()
                return True
            return False
        # Already on the navigation list: go back to Presets (the home screen).
        if self.listbook.GetSelection() != 0:
            self._goto(0)
            return True
        return False

    def _on_close(self, event) -> None:
        if event.CanVeto() and not self._confirm_discard():
            event.Veto()
            return
        self.Destroy()

    # -- menu -----------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        new_item = file_menu.Append(wx.ID_NEW, "&New Preset\tCtrl+N")
        open_item = file_menu.Append(wx.ID_OPEN, "&Open Preset File...\tCtrl+O")
        save_item = file_menu.Append(wx.ID_SAVE, "&Save Preset\tCtrl+S")
        export_item = file_menu.Append(wx.ID_SAVEAS, "&Export Preset to File...")
        reset_item = file_menu.Append(wx.ID_REVERT, "&Reset to Default Preset")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        menubar.Append(file_menu, "&File")

        go_menu = wx.Menu()
        back_item = go_menu.Append(wx.ID_ANY, "&Back to Presets\tCtrl+B")
        go_menu.AppendSeparator()
        titles = ["Presets"] + [s.display_name for s in SLOT_LAYOUT]
        self._go_items = []
        for i, title in enumerate(titles):
            accel = f"\tCtrl+{i + 1}" if i < 9 else ""
            item = go_menu.Append(wx.ID_ANY, f"{title}{accel}")
            self.Bind(wx.EVT_MENU, lambda e, idx=i: self._goto(idx), item)
        menubar.Append(go_menu, "&Go")

        settings_menu = wx.Menu()
        self.dark_item = settings_menu.AppendCheckItem(wx.ID_ANY, "&Dark Mode")
        self.dark_item.Check(self.dark_mode)
        settings_menu.AppendSeparator()
        folder_item = settings_menu.Append(wx.ID_ANY, "User Presets &Folder...")
        device_item = settings_menu.Append(wx.ID_ANY, "De&vice Settings and Modes...")
        menubar.Append(settings_menu, "&Settings")

        device_menu = wx.Menu()
        ports_item = device_menu.Append(wx.ID_ANY, "Detect &Ports...")
        menubar.Append(device_menu, "De&vice")

        help_menu = wx.Menu()
        keys_item = help_menu.Append(wx.ID_ANY, "&Keyboard Commands\tF1")
        about_item = help_menu.Append(wx.ID_ABOUT, "&About")
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self._on_new, new_item)
        self.Bind(wx.EVT_MENU, self._on_open_file, open_item)
        self.Bind(wx.EVT_MENU, self._on_save, save_item)
        self.Bind(wx.EVT_MENU, self._on_export_file, export_item)
        self.Bind(wx.EVT_MENU, self._on_reset, reset_item)
        self.Bind(wx.EVT_MENU, lambda e: self._goto_view("presets"), back_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)
        self.Bind(wx.EVT_MENU, self._on_toggle_dark, self.dark_item)
        self.Bind(wx.EVT_MENU, self._on_presets_folder, folder_item)
        self.Bind(wx.EVT_MENU, self._on_device_settings, device_item)
        self.Bind(wx.EVT_MENU, self._on_ports, ports_item)
        self.Bind(wx.EVT_MENU, self._on_keys, keys_item)
        self.Bind(wx.EVT_MENU, self._on_about, about_item)

    # -- preset actions -------------------------------------------------------

    def _on_open_preset(self, preset: Preset) -> None:
        """Load a preset into the editor and show the Amp page (no discard prompt)."""
        self.buffer.load_preset(preset)
        self._refresh_block_pages()
        self._dirty = False
        self._goto_view("amp")
        self.status.SetStatusText(f"Loaded preset: {preset.meta.get('name', '')}")

    def _guarded_open(self, preset: Preset) -> None:
        """Open a preset, first offering to save any unsaved changes."""
        if self._confirm_discard():
            self._on_open_preset(preset)

    def _on_new(self, event) -> None:
        if not self._confirm_discard():
            return
        preset = Preset.load_default(self.catalog.data_dir)
        preset.meta = {"name": "New Preset", "author": ""}
        self._on_open_preset(preset)
        self.status.SetStatusText("Started a new preset. Edit the blocks, then Save (Ctrl+S).")

    def _on_save(self, event) -> bool:
        """Save the current tone into the user preset library.  Returns True if saved."""
        default_name = self.buffer.preset.meta.get("name", "My Preset")
        with wx.TextEntryDialog(self, "Save current tone as:", "Save Preset", default_name) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return False
            name = dlg.GetValue().strip()
        if not name:
            return False
        self.buffer.preset.meta["name"] = name
        self.library.save(self.buffer.preset, name)
        self._dirty = False
        self._refresh_presets_page()
        self.status.SetStatusText(f"Saved preset '{name}' to your library.")
        return True

    def _on_open_file(self, event) -> None:
        if not self._confirm_discard():
            return
        with wx.FileDialog(
            self, "Open preset file",
            wildcard="Preset files (*.json)|*.json|All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            preset = Preset.from_json(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - surface any load error to the user
            wx.MessageBox(f"Could not open preset:\n{exc}", "Error", wx.ICON_ERROR)
            return
        self._on_open_preset(preset)

    def _on_export_file(self, event) -> None:
        with wx.FileDialog(
            self, "Export preset to file", wildcard="Preset files (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            path.write_text(json.dumps(self.buffer.preset.to_json(), indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not export preset:\n{exc}", "Error", wx.ICON_ERROR)
            return
        self.status.SetStatusText(f"Exported preset to {path.name}")

    def _on_reset(self, event) -> None:
        if not self._confirm_discard():
            return
        self._on_open_preset(Preset.load_default(self.catalog.data_dir))
        self.status.SetStatusText("Reset to default preset.")

    def _refresh_presets_page(self) -> None:
        page = self.listbook.GetPage(0)
        if isinstance(page, PresetsPanel):
            page.reload()

    # -- settings / device ----------------------------------------------------

    def _on_toggle_dark(self, event) -> None:
        self.dark_mode = self.dark_item.IsChecked()
        self._apply_theme()
        self.status.SetStatusText("Dark mode on." if self.dark_mode else "Dark mode off.")

    def _on_presets_folder(self, event) -> None:
        self.library.ensure_user_dir()
        wx.MessageBox(
            "Your saved presets are stored here:\n\n"
            f"{self.library.user_dir}\n\n"
            "Use 'Save Preset' (Ctrl+S) to save the tone you are editing.",
            "User presets folder", wx.ICON_INFORMATION,
        )

    def _on_device_settings(self, event) -> None:
        wx.MessageBox(
            "Device settings and footswitch modes live on the pedal and become available "
            "once a live connection is enabled.\n\n"
            "Planned here: global tempo, tuner, footswitch/pedal modes, and other device "
            "settings — alongside the Global page, which already holds tempo and the tweak "
            "assignment.\n\n"
            "Live control is pending completion of the on-wire message format "
            "(see docs/protocol.md).",
            "Device settings and modes", wx.ICON_INFORMATION,
        )

    def _on_ports(self, event) -> None:
        ports = list_serial_ports()
        likely = {p for p, _ in find_firehawk_ports()}
        if ports:
            lines = [
                f"{dev}  —  {desc}" + ("   (likely Firehawk)" if dev in likely else "")
                for dev, desc in ports
            ]
            body = "\n".join(lines)
        else:
            body = ("No serial ports detected. Pair the Firehawk over Bluetooth so it\n"
                    "appears as a COM port, then try again.")
        body += (
            "\n\nLive control over the port is not enabled yet — the on-wire message\n"
            "format is still being finalised (see docs/protocol.md). Offline editing,\n"
            "loading and saving presets all work now."
        )
        wx.MessageBox(body, "Detected serial ports", wx.ICON_INFORMATION)

    def _on_keys(self, event) -> None:
        commands = [
            ("Ctrl+N", "New preset"),
            ("Ctrl+O", "Open preset file"),
            ("Ctrl+S", "Save preset to your library"),
            ("Ctrl+1 .. Ctrl+9", "Jump to Presets, Wah, Compressor, Noise Gate, Amp,"
                                 " Cabinet, EQ, FX 1, FX 2"),
            ("Ctrl+B", "Back to the Presets list"),
            ("Escape", "Back one level: page controls -> block list -> Presets"),
            ("Tab / Shift+Tab", "Move between controls on a page"),
            ("Up / Down arrows", "Move through the block list, or a dropdown's options"),
            ("Left / Right arrows", "Adjust a slider; Page Up/Down for larger steps"),
            ("Space", "Toggle a checkbox"),
            ("Alt + underlined letter", "Open a menu (File, Go, Settings, Device, Help)"),
            ("F1", "Show this list"),
        ]
        width = max(len(k) for k, _ in commands)
        body = "\n".join(f"{k.ljust(width)}   {d}" for k, d in commands)
        dlg = wx.Dialog(self, title="Keyboard commands", size=(680, 460))
        text = wx.TextCtrl(dlg, value=body, style=wx.TE_MULTILINE | wx.TE_READONLY)
        set_accessible_name(text, "Keyboard commands list")
        theme.apply(dlg, self.dark_mode)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(text, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(dlg.CreateButtonSizer(wx.OK), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        dlg.SetSizer(sizer)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_about(self, event) -> None:
        wx.MessageBox(
            f"{APP_TITLE}\n\n"
            "An accessible, screen-reader-first controller for the Line 6 Firehawk FX.\n"
            f"Loaded {len(self.catalog)} models.\n\n"
            "Editing works offline now; hardware control is in progress.",
            "About", wx.ICON_INFORMATION,
        )
