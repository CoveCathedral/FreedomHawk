"""A panel presenting one signal-chain slot for editing.

Layout (all keyboard-navigable, each control carrying an accessible name):

* an **Enabled** checkbox (for blocks that can be bypassed);
* a **Model** chooser (for swappable slots); changing it rebuilds the parameters;
* one labelled control per parameter, built from the model metadata.
"""

from __future__ import annotations

from typing import Callable

import wx

from ..model import EditBuffer, ModelCatalog, ModelSpec, SlotDef
from .accessibility import set_accessible_name
from .controls import ParamControl

# Parameters handled by the dedicated Enabled/Model widgets, not the generic list.
_HANDLED = {"@model", "@enabled"}


class BlockPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        slot: SlotDef,
        buffer: EditBuffer,
        catalog: ModelCatalog,
        device_id: int | None = None,
        status: "callable | None" = None,
        themer: Callable[[wx.Window], None] | None = None,
    ):
        super().__init__(parent)
        self.slot = slot
        self.buffer = buffer
        self.catalog = catalog
        self.device_id = device_id
        self._status = status
        self._themer = themer
        self._params: list[ParamControl] = []
        self._model_ids: list[str] = []

        self.root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.root)

        self._build_header()
        self.param_panel = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.param_panel.SetScrollRate(0, 12)
        self.param_sizer = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        self.param_sizer.AddGrowableCol(1, 1)
        self.param_panel.SetSizer(self.param_sizer)
        self.root.Add(self.param_panel, 1, wx.EXPAND | wx.ALL, 8)

        self._rebuild_params()

    # -- header (enabled + model) --------------------------------------------

    def _build_header(self) -> None:
        header = wx.BoxSizer(wx.HORIZONTAL)
        model = self._effective_model()

        # Enabled checkbox, only where the block supports bypass.
        self.enable_cb = None
        if self._supports_enable(model):
            # Name lives in the label (a native checkbox ignores SetName for its name).
            self.enable_cb = wx.CheckBox(self, label=f"{self.slot.display_name} enabled")
            self.enable_cb.SetValue(self.buffer.block(self.slot.id).enabled)
            self.enable_cb.Bind(wx.EVT_CHECKBOX, self._on_enable)
            header.Add(self.enable_cb, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)

        # Model chooser, only for swappable slots with more than one choice.
        self.model_choice = None
        if self.slot.swappable:
            label = wx.StaticText(self, label="Model:")
            header.Add(label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
            self.model_choice = wx.Choice(self)
            set_accessible_name(self.model_choice, f"{self.slot.display_name} model")
            self._populate_models()
            self.model_choice.Bind(wx.EVT_CHOICE, self._on_model)
            header.Add(self.model_choice, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)

        if header.GetItemCount():
            self.root.Add(header, 0, wx.EXPAND | wx.ALL, 6)

    def _populate_models(self) -> None:
        assert self.model_choice is not None
        labels: list[str] = []
        self._model_ids = []
        seen: set[str] = set()
        current = self.buffer.block(self.slot.id).model_id
        current_index = 0
        for group in self.catalog.models_for_slot(self.slot.id, self.device_id):
            if "testing" in group.name.lower():
                continue  # developer-only duplicate group (e.g. "PODX3 (testing)")
            for m in group.models:
                if m.symbolic_id in seen:
                    continue  # a model may appear in several groups; list it once
                seen.add(m.symbolic_id)
                labels.append(f"{m.display_name}  [{group.name}]")
                self._model_ids.append(m.symbolic_id)
                if m.symbolic_id == current:
                    current_index = len(self._model_ids) - 1
        self.model_choice.Set(labels)
        if labels:
            self.model_choice.SetSelection(current_index)

    # -- parameters -----------------------------------------------------------

    def _rebuild_params(self) -> None:
        self.param_sizer.Clear(delete_windows=True)
        self._params = []
        model = self._effective_model()
        if model is None:
            note = wx.StaticText(self.param_panel, label="No editable parameters.")
            self.param_sizer.Add(note, 0, wx.ALL, 6)
            self.param_sizer.AddStretchSpacer()
        else:
            block = self.buffer.block(self.slot.id)
            for spec in model.params:
                if spec.symbolic_id in _HANDLED:
                    continue
                value = block.get(spec.symbolic_id, spec.default)
                pc = ParamControl(self.param_panel, spec, value, self._on_param)
                self.param_sizer.Add(pc.label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
                self.param_sizer.Add(pc.control, 1, wx.EXPAND | wx.RIGHT, 6)
                self._params.append(pc)
        if self._themer is not None:
            self._themer(self.param_panel)
        self.param_panel.Layout()
        self.param_panel.FitInside()

    def refresh(self) -> None:
        """Re-sync this page to the current edit buffer (e.g. after loading a preset)."""
        if self.enable_cb is not None:
            self.enable_cb.SetValue(self.buffer.block(self.slot.id).enabled)
        if self.model_choice is not None:
            current = self.buffer.block(self.slot.id).model_id
            if current in self._model_ids:
                self.model_choice.SetSelection(self._model_ids.index(current))
        self._rebuild_params()

    # -- events ---------------------------------------------------------------

    def _on_enable(self, event: wx.CommandEvent) -> None:
        self.buffer.set_enabled(self.slot.id, event.IsChecked())
        self._announce(f"{self.slot.display_name} {'enabled' if event.IsChecked() else 'bypassed'}")

    def _on_model(self, event: wx.CommandEvent) -> None:
        idx = self.model_choice.GetSelection()
        if 0 <= idx < len(self._model_ids):
            symbolic_id = self._model_ids[idx]
            self.buffer.set_model(self.slot.id, symbolic_id)
            self._rebuild_params()
            model = self.catalog.model(symbolic_id)
            self._announce(f"{self.slot.display_name} model {model.display_name if model else symbolic_id}")

    def _on_param(self, param_id: str, value) -> None:
        stored = self.buffer.set_param(self.slot.id, param_id, value)
        spec = self.buffer.param_spec(self.slot.id, param_id)
        name = spec.display_name if spec else param_id
        self._announce(f"{name} {self._format(stored)}")

    # -- helpers --------------------------------------------------------------

    def _effective_model(self) -> ModelSpec | None:
        model = self.buffer.model_of(self.slot.id)
        if model is None and self.slot.id == "global":
            model = self.catalog.model("@global_params")
        return model

    def _supports_enable(self, model: ModelSpec | None) -> bool:
        if model is not None and model.param("@enabled") is not None:
            return True
        return "@enabled" in self.buffer.block(self.slot.id).values

    @staticmethod
    def _format(value) -> str:
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    def _announce(self, message: str) -> None:
        if self._status is not None:
            self._status(message)
