"""DeviceSession: the gated bridge between the edit buffer and the pedal.

It subscribes to :class:`~firehawk.model.EditBuffer` changes, encodes each edit with
:func:`firehawk.protocol.addressing.encode_edit` (which routes to the right ToneMatch
command), records it in an outbox, and — only when transmission is explicitly enabled —
wraps it in a transport header + serial frame and writes it to the transport.

**Safety gate:** ``transmit_enabled`` is False by default and must be turned on
deliberately.  Until the on-wire format is validated against a real capture, nothing is
sent to hardware; the session still encodes and logs everything, so you can inspect
exactly what *would* be transmitted (and compare it to a capture later).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..model import EditBuffer, ModelCatalog, SymbolTable
from ..model.catalog import DATA_DIR
from ..protocol import Frame, TransportHeader
from ..protocol.addressing import EncodedEdit, encode_edit

# The transport-header port/type for the ToneMatch editor endpoint are not yet confirmed
# (see docs/protocol.md). These placeholders only matter once transmission is enabled and
# validated; the ToneMatch command payload itself is confirmed.
TONEMATCH_PORT_TODO = 0


@dataclass
class OutboxEntry:
    group: str
    param: str
    value: object
    edit: EncodedEdit | None       # None if the edit couldn't be mapped
    transmitted: bool


class DeviceSession:
    def __init__(
        self,
        catalog: ModelCatalog,
        symbol_table: SymbolTable | None = None,
        transport=None,
    ):
        self.catalog = catalog
        self.symbol_table = symbol_table or SymbolTable.load(DATA_DIR / "defaultSymbolTable.bin")
        self.transport = transport
        #: Safety gate — nothing is written to hardware unless this is explicitly True.
        self.transmit_enabled = False
        self.seq = 0
        self.outbox: list[OutboxEntry] = []
        #: Optional observer called after each edit is processed (for the UI log).
        self.on_log: Callable[[OutboxEntry], None] | None = None

    # -- wiring ---------------------------------------------------------------

    def attach(self, edit_buffer: EditBuffer) -> None:
        edit_buffer.add_listener(self.handle_edit)

    @property
    def connected(self) -> bool:
        return self.transport is not None and self.transport.is_open

    # -- encoding -------------------------------------------------------------

    def _model_numeric_id(self, symbolic_id: str) -> int | None:
        model = self.catalog.model(symbolic_id)
        return model.numeric_id if model else None

    def encode(self, group: str, param: str, value) -> EncodedEdit | None:
        """Encode an edit to its ToneMatch command without transmitting (preview)."""
        return encode_edit(self.symbol_table.index, self._model_numeric_id, group, param, value)

    # -- edit handling --------------------------------------------------------

    def handle_edit(self, group: str, param: str, value) -> OutboxEntry:
        edit = self.encode(group, param, value)
        transmitted = False
        if edit is not None and self.transmit_enabled and self.connected:
            self._transmit(edit.message)
            transmitted = True
        entry = OutboxEntry(group, param, value, edit, transmitted)
        self.outbox.append(entry)
        if self.on_log is not None:
            self.on_log(entry)
        return entry

    # -- transmission ---------------------------------------------------------

    def frame_for(self, tonematch_message: bytes) -> bytes:
        """Wrap a ToneMatch command in the transport header + serial frame."""
        header = TransportHeader(
            msg_type=0, field_c=len(tonematch_message),
            addr_d=TONEMATCH_PORT_TODO, addr_e=TONEMATCH_PORT_TODO,
        ).pack()
        payload = header + tonematch_message
        frame = Frame(seq=self.seq & 0xFF, ack=0, payload=payload).build()
        self.seq = (self.seq + 1) & 0xFF
        return frame

    def _transmit(self, tonematch_message: bytes) -> None:
        self.transport.write(self.frame_for(tonematch_message))
