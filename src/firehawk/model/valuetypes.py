"""Core value-type semantics and parameter/model specifications.

Every editable thing on the pedal is described by static data shipped inside the
original app (``assets/*.models``).  This module turns that raw JSON into typed,
self-describing Python objects so the UI layer can build a correctly labelled and
correctly ranged control for each parameter -- which is what makes the app usable
with a screen reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ValueType(IntEnum):
    """The ``valueType`` field found on every parameter in ``*.models``.

    Determined empirically across all 261 models / 1883 parameters:

    * ``INT``        -- an integer/enumerated choice with an integer ``min``..``max``
                        range (e.g. cabinet ``@mic`` 0..3, delay ``SyncSelect``).
                        Presented as a spin control or, where option names are
                        known, a combo box.
    * ``CONTINUOUS`` -- a continuous value with a floating ``min``..``max`` range.
                        Usually normalised 0.0..1.0, but sometimes a real-world
                        range (e.g. gate ``Thresh`` in dB).  Presented as a slider.
    * ``BOOL``       -- a two-state toggle (``min`` False, ``max`` True).  Presented
                        as a checkbox.
    * ``STRING``     -- a symbolic string reference (e.g. ``@tweakgroup`` names
                        another block).  Presented as a combo box of valid targets.
    """

    INT = 0
    CONTINUOUS = 1
    BOOL = 2
    STRING = 3


# Parameter symbolic IDs starting with "@" are structural/control attributes of a
# block (model selection, enable toggle, mix, routing) rather than sound knobs.
def is_control_param(symbolic_id: str) -> bool:
    """True for structural block attributes such as ``@model``/``@enabled``/``@mix``."""
    return symbolic_id.startswith("@")


_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def humanize(symbolic_id: str) -> str:
    """Turn a symbolic ID into a readable label when no ``name`` is provided.

    ``@mixtype`` -> "Mix Type", ``FbackL`` -> "Fback L".  Used only as a fallback;
    the model data supplies real display names for almost every parameter.
    """
    text = symbolic_id.lstrip("@")
    text = text.replace("_", " ").replace("/", " / ")
    text = _CAMEL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1].upper() + text[1:] if text else symbolic_id


@dataclass(frozen=True)
class ParamSpec:
    """Specification of a single editable parameter within a model."""

    symbolic_id: str
    value_type: ValueType
    minimum: float | int | bool
    maximum: float | int | bool
    default: float | int | bool
    name: str | None = None
    persist: int = 0
    tweak: int | None = None
    #: Optional human-readable labels for INT/enum values, indexed by (value - minimum).
    #: Populated where known (e.g. from native display-format tables); may be empty.
    options: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display_name(self) -> str:
        """The label a screen reader should announce for this control."""
        return self.name or humanize(self.symbolic_id)

    @property
    def is_control(self) -> bool:
        return is_control_param(self.symbolic_id)

    @property
    def is_enable_toggle(self) -> bool:
        return self.symbolic_id == "@enabled"

    def clamp(self, value: Any) -> Any:
        """Constrain *value* to this parameter's declared range and type."""
        if self.value_type is ValueType.BOOL:
            return bool(value)
        if self.value_type is ValueType.STRING:
            return "" if value is None else str(value)
        if value < self.minimum:
            return self.minimum
        if value > self.maximum:
            return self.maximum
        if self.value_type is ValueType.INT:
            return int(round(value))
        return value

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "ParamSpec":
        vt = ValueType(int(raw["valueType"]))
        return cls(
            symbolic_id=raw["symbolicID"],
            value_type=vt,
            minimum=raw["min"],
            maximum=raw["max"],
            default=raw["default"],
            name=raw.get("name"),
            persist=int(raw.get("persist", 0)),
            tweak=raw.get("tweak"),
        )


@dataclass(frozen=True)
class ModelSpec:
    """Specification of a selectable model (an amp, cab, effect, reverb, wah...)."""

    symbolic_id: str
    numeric_id: int
    name: str
    category: int | None
    shortname: str | None = None
    icon: str | None = None
    #: Hardware product IDs this model is restricted to; empty tuple = available on all.
    devices: tuple[int, ...] = field(default_factory=tuple)
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)
    #: Model-level extras kept verbatim (e.g. amp ``cablink``, ``cabmic``, ``cabER``).
    extras: dict[str, Any] = field(default_factory=dict)

    def param(self, symbolic_id: str) -> ParamSpec | None:
        for p in self.params:
            if p.symbolic_id == symbolic_id:
                return p
        return None

    @property
    def display_name(self) -> str:
        return self.name or self.symbolic_id

    def available_on(self, device_id: int | None) -> bool:
        """Whether this model is offered on the given hardware product ID.

        A model with no ``devices`` restriction is available everywhere.  When
        *device_id* is None (unknown hardware) every model is offered.
        """
        if not self.devices or device_id is None:
            return True
        return device_id in self.devices

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "ModelSpec":
        standard = {
            "symbolicID", "id", "name", "category",
            "shortname", "icon", "devices", "params",
        }
        params = tuple(ParamSpec.from_json(p) for p in raw.get("params", []))
        devices = tuple(raw["devices"]) if raw.get("devices") else ()
        extras = {k: v for k, v in raw.items() if k not in standard}
        return cls(
            symbolic_id=raw["symbolicID"],
            numeric_id=int(raw["id"]),
            name=raw.get("name", raw["symbolicID"]),
            category=raw.get("category"),
            shortname=raw.get("shortname"),
            icon=raw.get("icon"),
            devices=devices,
            params=params,
            extras=extras,
        )
