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

from ..config import AppSettings, all_views
from ..device import DeviceSession
from ..model import EditBuffer, ModelCatalog, Preset, PresetLibrary, SLOT_LAYOUT
from ..transport import SerialTransport
from ..transport.serialport import find_firehawk_ports, list_serial_ports
from . import theme
from .accessibility import set_accessible_name
from .blockpanel import BlockPanel
from .drumspanel import DrumsPanel
from .metronomepanel import MetronomePanel
from .presetspanel import PresetsPanel
from .tunerpanel import TunerPanel

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
        self.settings = AppSettings()
        self.buffer = EditBuffer(self.catalog)
        self.library = PresetLibrary(self.catalog.data_dir)
        self._dirty = False
        self.buffer.add_listener(self._on_buffer_change)

        # The gated bridge to the pedal. It encodes and logs every edit; it only
        # transmits when the user explicitly enables it (off by default).
        self.session = DeviceSession(self.catalog)
        self.session.attach(self.buffer)
        self.session.on_log = self._on_encoded_edit

        self.status = self.CreateStatusBar()
        self.status.SetStatusText("Ready — editing offline. Presets load and save locally.")

        self.listbook = wx.Listbook(self, style=wx.LB_LEFT)
        self._view_ids: list[str] = []
        self.tuner_page: TunerPanel | None = None
        self.metronome_page: MetronomePanel | None = None
        self.drums_page: DrumsPanel | None = None
        self._build_pages()
        self._build_menu()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.listbook, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.Centre()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.listbook.Bind(wx.EVT_LISTBOOK_PAGE_CHANGED, self._on_page_changed)
        self._apply_theme()

    def _on_page_changed(self, event) -> None:
        # Stop any tuner tone when navigating away from the Tuner page.
        sel = self.listbook.GetSelection()
        if (sel != wx.NOT_FOUND and self.tuner_page is not None
                and self.listbook.GetPage(sel) is not self.tuner_page):
            self.tuner_page.stop()
        event.Skip()

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
        """Build the notebook pages in the user's saved order (Settings > Arrange Tabs)."""
        self.listbook.DeleteAllPages()
        self._view_ids = []
        self.tuner_page = None
        self.metronome_page = None
        self.drums_page = None
        titles = dict(all_views())
        slots_by_id = {s.id: s for s in SLOT_LAYOUT}

        for view_id in self.settings.page_order():
            if view_id == "presets":
                page = PresetsPanel(
                    self.listbook, self.library, self.catalog,
                    on_open=self._guarded_open,
                    get_current=lambda: self.buffer.preset,
                    status=self.status.SetStatusText,
                )
            elif view_id == "tuner":
                page = TunerPanel(self.listbook, status=self.status.SetStatusText)
                self.tuner_page = page
            elif view_id == "metronome":
                page = MetronomePanel(self.listbook, status=self.status.SetStatusText)
                self.metronome_page = page
            elif view_id == "drums":
                page = DrumsPanel(self.listbook, settings=self.settings,
                                  status=self.status.SetStatusText)
                self.drums_page = page
            elif view_id in slots_by_id:
                page = BlockPanel(
                    self.listbook, slots_by_id[view_id], self.buffer, self.catalog,
                    device_id=self.device_id, status=self.status.SetStatusText,
                    themer=self._themer,
                )
            else:
                continue
            self.listbook.AddPage(page, titles.get(view_id, view_id))
            self._view_ids.append(view_id)

        if self.listbook.GetPageCount():
            self.listbook.SetSelection(0)

    def _rebuild_after_reorder(self) -> None:
        """Apply the saved tab order by moving existing pages (no rebuild, no flicker)."""
        self._apply_page_order(self.settings.page_order())

    def _apply_page_order(self, new_order: list[str]) -> None:
        """Reorder the notebook by re-seating the *existing* page windows.

        The pages are reused rather than recreated, so they keep their state and theme
        and nothing flashes.  Only the (invisible) Go-menu labels are refreshed.
        """
        selected_view = None
        sel = self.listbook.GetSelection()
        if 0 <= sel < len(self._view_ids):
            selected_view = self._view_ids[sel]
        win_by_id = {vid: self.listbook.GetPage(i) for i, vid in enumerate(self._view_ids)}
        titles = dict(all_views())

        self.Freeze()  # suppress painting until the whole reorder is done
        try:
            for i in reversed(range(self.listbook.GetPageCount())):
                self.listbook.RemovePage(i)  # removes the page but keeps the window alive
            self._view_ids = []
            for view_id in new_order:
                win = win_by_id.pop(view_id, None)
                if win is None:
                    continue
                self.listbook.AddPage(win, titles.get(view_id, view_id))
                self._view_ids.append(view_id)
            for view_id, win in win_by_id.items():  # any view not named in new_order
                self.listbook.AddPage(win, titles.get(view_id, view_id))
                self._view_ids.append(view_id)
            if selected_view in self._view_ids:
                self.listbook.SetSelection(self._view_ids.index(selected_view))
            elif self._view_ids:
                self.listbook.SetSelection(0)
        finally:
            self.Thaw()
        self._relabel_go_menu()

    def _relabel_go_menu(self) -> None:
        """Update the Go menu's jump labels/accelerators to the current tab order."""
        titles = dict(all_views())
        for i, item in enumerate(self._go_view_items):
            if i < len(self._view_ids):
                view_id = self._view_ids[i]
                accel = f"\tCtrl+{i + 1}" if i < 9 else ""
                item.SetItemLabel(f"{titles.get(view_id, view_id)}{accel}")

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
        home = self._view_ids.index("presets") if "presets" in self._view_ids else 0
        if self.listbook.GetSelection() != home:
            self._goto(home)
            return True
        return False

    def _on_close(self, event) -> None:
        if event.CanVeto() and not self._confirm_discard():
            event.Veto()
            return
        if self.tuner_page is not None:
            self.tuner_page.dispose()
        if self.metronome_page is not None:
            self.metronome_page.dispose()
        if self.drums_page is not None:
            self.drums_page.dispose()
        if self.session.transport is not None:
            try:
                self.session.transport.close()
            except Exception:  # noqa: BLE001
                pass
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
        titles = dict(all_views())
        self._go_view_items = []
        for i, view_id in enumerate(self._view_ids):
            accel = f"\tCtrl+{i + 1}" if i < 9 else ""
            item = go_menu.Append(wx.ID_ANY, f"{titles.get(view_id, view_id)}{accel}")
            self.Bind(wx.EVT_MENU, lambda e, idx=i: self._goto(idx), item)
            self._go_view_items.append(item)
        menubar.Append(go_menu, "&Go")

        settings_menu = wx.Menu()
        self.dark_item = settings_menu.AppendCheckItem(wx.ID_ANY, "&Dark Mode")
        self.dark_item.Check(self.dark_mode)
        arrange_item = settings_menu.Append(wx.ID_ANY, "&Arrange Tabs...")
        settings_menu.AppendSeparator()
        folder_item = settings_menu.Append(wx.ID_ANY, "User Presets &Folder...")
        device_item = settings_menu.Append(wx.ID_ANY, "De&vice Settings and Modes...")
        menubar.Append(settings_menu, "&Settings")

        device_menu = wx.Menu()
        connect_item = device_menu.Append(wx.ID_ANY, "&Connect to Pedal...")
        ports_item = device_menu.Append(wx.ID_ANY, "Detect &Ports...")
        device_menu.AppendSeparator()
        self.transmit_item = device_menu.AppendCheckItem(
            wx.ID_ANY, "&Transmit Edits to Pedal (unvalidated!)")
        messages_item = device_menu.Append(wx.ID_ANY, "View &Outgoing Messages...")
        menubar.Append(device_menu, "De&vice")

        help_menu = wx.Menu()
        keys_item = help_menu.Append(wx.ID_ANY, "&Keyboard Commands\tF1")
        metronome_help_item = help_menu.Append(wx.ID_ANY, "Using the Me&tronome...")
        drums_help_item = help_menu.Append(wx.ID_ANY, "Using the &Drum Looper...")
        music_item = help_menu.Append(wx.ID_ANY, "Playing Along with &Music...")
        about_item = help_menu.Append(wx.ID_ABOUT, "&About")
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)
        # Keep the transmit checkbox in sync with session state across menu rebuilds.
        self.transmit_item.Check(self.session.transmit_enabled)
        self.Bind(wx.EVT_MENU, self._on_new, new_item)
        self.Bind(wx.EVT_MENU, self._on_open_file, open_item)
        self.Bind(wx.EVT_MENU, self._on_save, save_item)
        self.Bind(wx.EVT_MENU, self._on_export_file, export_item)
        self.Bind(wx.EVT_MENU, self._on_reset, reset_item)
        self.Bind(wx.EVT_MENU, lambda e: self._goto_view("presets"), back_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)
        self.Bind(wx.EVT_MENU, self._on_toggle_dark, self.dark_item)
        self.Bind(wx.EVT_MENU, self._on_arrange_tabs, arrange_item)
        self.Bind(wx.EVT_MENU, self._on_presets_folder, folder_item)
        self.Bind(wx.EVT_MENU, self._on_device_settings, device_item)
        self.Bind(wx.EVT_MENU, self._on_connect, connect_item)
        self.Bind(wx.EVT_MENU, self._on_ports, ports_item)
        self.Bind(wx.EVT_MENU, self._on_toggle_transmit, self.transmit_item)
        self.Bind(wx.EVT_MENU, self._on_view_messages, messages_item)
        self.Bind(wx.EVT_MENU, self._on_keys, keys_item)
        self.Bind(wx.EVT_MENU, self._on_metronome_help, metronome_help_item)
        self.Bind(wx.EVT_MENU, self._on_drums_help, drums_help_item)
        self.Bind(wx.EVT_MENU, self._on_music, music_item)
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
        for i in range(self.listbook.GetPageCount()):
            page = self.listbook.GetPage(i)
            if isinstance(page, PresetsPanel):
                page.reload()
                return

    # -- settings / device ----------------------------------------------------

    def _on_toggle_dark(self, event) -> None:
        self.dark_mode = self.dark_item.IsChecked()
        self._apply_theme()
        self.status.SetStatusText("Dark mode on." if self.dark_mode else "Dark mode off.")

    def _on_arrange_tabs(self, event) -> None:
        """Accessible reorder dialog: a list where Alt+Up / Alt+Down move the selected tab."""
        titles = dict(all_views())
        order = list(self._view_ids)

        dlg = wx.Dialog(self, title="Arrange tabs", size=(380, 500))
        intro = wx.StaticText(dlg, label=(
            "Choose where each tab appears. Select a tab, then press Alt+Up or Alt+Down "
            "to move it (or use the buttons below). The first tab is the one you land on "
            "at startup; Ctrl+1 through Ctrl+9 jump to the first nine. Press OK to apply."))
        intro.Wrap(340)
        listbox = wx.ListBox(dlg, choices=[titles.get(v, v) for v in order], style=wx.LB_SINGLE)
        set_accessible_name(listbox, "Tab order")
        if order:
            listbox.SetSelection(0)

        up_btn = wx.Button(dlg, label="Move &Up")
        down_btn = wx.Button(dlg, label="Move &Down")

        def move(delta: int) -> None:
            i = listbox.GetSelection()
            j = i + delta
            if i == wx.NOT_FOUND or not (0 <= j < len(order)):
                return
            order[i], order[j] = order[j], order[i]
            listbox.Set([titles.get(v, v) for v in order])
            listbox.SetSelection(j)
            listbox.SetFocus()

        def on_key(evt: wx.KeyEvent) -> None:
            # Alt+Up / Alt+Down reorder in place, so keyboard users never leave the list.
            if evt.AltDown() and evt.GetKeyCode() == wx.WXK_UP:
                move(-1)
            elif evt.AltDown() and evt.GetKeyCode() == wx.WXK_DOWN:
                move(1)
            else:
                evt.Skip()

        listbox.Bind(wx.EVT_KEY_DOWN, on_key)
        up_btn.Bind(wx.EVT_BUTTON, lambda e: move(-1))
        down_btn.Bind(wx.EVT_BUTTON, lambda e: move(1))

        btns = wx.BoxSizer(wx.HORIZONTAL)
        btns.Add(up_btn, 0, wx.RIGHT, 6)
        btns.Add(down_btn, 0)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(intro, 0, wx.ALL, 10)
        sizer.Add(listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btns, 0, wx.ALL, 10)
        sizer.Add(dlg.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dlg.SetSizer(sizer)
        theme.apply(dlg, self.dark_mode)

        if dlg.ShowModal() == wx.ID_OK and order != self._view_ids:
            self.settings.set_page_order(order)
            self._rebuild_after_reorder()
            self.status.SetStatusText("Tab order updated.")
        dlg.Destroy()

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

    # -- device session (staged, gated) ---------------------------------------

    def _on_encoded_edit(self, entry) -> None:
        """Status feedback as edits are encoded (and, if enabled, transmitted)."""
        if entry.edit is None:
            self.status.SetStatusText(f"{entry.group}/{entry.param}: no device mapping yet")
            return
        verb = "Sent" if entry.transmitted else "Staged"
        self.status.SetStatusText(f"{verb}: {entry.edit.kind} — {entry.edit.detail}")

    def _on_connect(self, event) -> None:
        ports = list_serial_ports()
        if not ports:
            wx.MessageBox(
                "No serial ports found. Pair the Firehawk over Bluetooth so it appears as a\n"
                "COM port, then try again.",
                "Connect to pedal", wx.ICON_INFORMATION)
            return
        likely = {p for p, _ in find_firehawk_ports()}
        labels = [f"{dev}  —  {desc}" + ("  (likely Firehawk)" if dev in likely else "")
                  for dev, desc in ports]
        dlg = wx.SingleChoiceDialog(self, "Choose the pedal's serial port:", "Connect to pedal", labels)
        if dlg.ShowModal() == wx.ID_OK:
            dev = ports[dlg.GetSelection()][0]
            try:
                transport = SerialTransport(dev)
                transport.open()
            except Exception as exc:  # noqa: BLE001
                wx.MessageBox(f"Could not open {dev}:\n{exc}", "Connect", wx.ICON_ERROR)
                dlg.Destroy()
                return
            self.session.transport = transport
            self.status.SetStatusText(f"Connected to {dev} (transmit still off — see Device menu).")
        dlg.Destroy()

    def _on_toggle_transmit(self, event) -> None:
        if self.transmit_item.IsChecked():
            ok = wx.MessageBox(
                "Enable transmitting your edits to the pedal?\n\n"
                "The on-wire format is reverse-engineered but NOT yet validated against a real\n"
                "capture, so this could send unexpected data to your hardware. Only enable this\n"
                "for testing once the protocol has been confirmed.\n\nEnable anyway?",
                "Transmit to pedal", wx.YES_NO | wx.ICON_WARNING) == wx.YES
            if not ok:
                self.transmit_item.Check(False)
                return
        self.session.transmit_enabled = self.transmit_item.IsChecked()
        self.status.SetStatusText(
            "Transmitting edits to the pedal." if self.session.transmit_enabled
            else "Transmit off — edits are staged only.")

    def _on_view_messages(self, event) -> None:
        lines = []
        for i, e in enumerate(self.session.outbox[-200:]):
            if e.edit is None:
                lines.append(f"{i:3}  {e.group}/{e.param} = {e.value}   (unmapped)")
            else:
                tag = "SENT" if e.transmitted else "staged"
                lines.append(f"{i:3}  [{tag}] {e.edit.kind:<12} {e.edit.detail}\n"
                             f"        payload: {e.edit.message.hex(' ')}")
        body = "\n".join(lines) or "No edits yet. Move a control to stage a message."
        dlg = wx.Dialog(self, title="Outgoing messages (staged)", size=(760, 480))
        text = wx.TextCtrl(dlg, value=body, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        set_accessible_name(text, "Outgoing messages")
        theme.apply(dlg, self.dark_mode)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(text, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(dlg.CreateButtonSizer(wx.OK), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        dlg.SetSizer(sizer)
        dlg.ShowModal()
        dlg.Destroy()

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
        titles = dict(all_views())
        jump_targets = ", ".join(titles.get(v, v) for v in self._view_ids[:9])
        commands = [
            ("Ctrl+N", "New preset"),
            ("Ctrl+O", "Open preset file"),
            ("Ctrl+S", "Save preset to your library"),
            ("Ctrl+1 .. Ctrl+9", f"Jump to the first nine tabs ({jump_targets})"),
            ("Ctrl+B", "Back to the Presets list"),
            ("Escape", "Back one level: page controls -> block list -> Presets"),
            ("Tab / Shift+Tab", "Move between controls on a page"),
            ("Up / Down arrows", "Move through the block list, or a dropdown's options"),
            ("Left / Right arrows", "Adjust a slider; Page Up/Down for larger steps"),
            ("Space", "Toggle a checkbox"),
            ("Alt + underlined letter", "Open a menu (File, Go, Settings, Device, Help)"),
            ("Settings > Arrange Tabs", "Reorder tabs — select one, then Alt+Up / Alt+Down"),
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

    def _on_metronome_help(self, event) -> None:
        wx.MessageBox(
            "Using the Metronome\n\n"
            "1. Set the Tempo (30-300 BPM). A screen reader announces the real BPM.\n"
            "2. Set Beats per measure; Subdivision adds eighth/triplet/sixteenth clicks\n"
            "   between beats. Tap Tempo sets the speed from your taps.\n"
            "3. For odd meters, check 'Non-standard meter' to reveal the Beat unit and an\n"
            "   Accent grouping field: type 2+2+3 (for a 7) to accent the groups. The\n"
            "   numbers must add up to the beats per measure. Unchecking it returns to\n"
            "   standard timing.\n"
            "4. Start/Stop begins and ends the click.\n\n"
            "The metronome keeps playing while you switch to other tabs, so you can keep\n"
            "time while editing a tone. Press Stop or close the app to end it.",
            "Using the Metronome", wx.ICON_INFORMATION)

    def _on_drums_help(self, event) -> None:
        wx.MessageBox(
            "Using the Drum Looper\n\n"
            "1. Kit: 'Synth (built-in)' works with no files; kit folders in Samples appear\n"
            "   in the list too. 'Import Drum Kit...' loads a kit folder from anywhere.\n"
            "2. Groove: 200 built-in patterns - the classics (Rock, Funk, Trap, 5/4, 7/8,\n"
            "   ...) plus numbered variations; names ending in 'fill' include a drum fill.\n"
            "   First-letter navigation works in the list.\n"
            "3. Edit Pattern... opens the step editor: pick a step with the Step dropdown\n"
            "   (arrow keys - steps are named by beat, like 'Bar 2, Beat 3'), then check\n"
            "   which parts hit there. Play auditions while you edit; Save keeps it,\n"
            "   Cancel or Escape discards. The time signature (odd meters too) is set here.\n"
            "4. Part + Mute this part silences a part live without erasing its steps.\n"
            "5. Set the Tempo and press Start. Changes apply on the next loop.\n\n"
            "The loop keeps playing across tabs. To use your own drum libraries, see the\n"
            "guide in docs/drum-kits.md. Samples of any length land exactly on the beat.",
            "Using the Drum Looper", wx.ICON_INFORMATION)

    def _on_music(self, event) -> None:
        wx.MessageBox(
            "Play along with your own music through the pedal\n\n"
            "The Firehawk FX is also a Bluetooth speaker. Once it's paired to this computer,\n"
            "you can send any audio to it — no setting in this app is needed:\n\n"
            "  1. Pair the Firehawk over Bluetooth (Windows Settings > Bluetooth & devices).\n"
            "  2. Open Windows Sound settings (right-click the speaker icon > Sound settings).\n"
            "  3. Set the Firehawk as the output/playback device.\n"
            "  4. Play a song in any media player — it comes out through the pedal, and you\n"
            "     play along on your guitar.\n\n"
            "This is separate from the control connection this app uses, so editing your tone\n"
            "and streaming music can happen at the same time. (The cloud-based automatic\n"
            "tone-matching from the old app is gone, but the play-along itself works.)",
            "Playing along with music", wx.ICON_INFORMATION)

    def _on_about(self, event) -> None:
        wx.MessageBox(
            f"{APP_TITLE}\n\n"
            "An accessible, screen-reader-first controller for the Line 6 Firehawk FX.\n"
            f"Loaded {len(self.catalog)} models.\n\n"
            "Editing works offline now; hardware control is in progress.",
            "About", wx.ICON_INFORMATION,
        )
