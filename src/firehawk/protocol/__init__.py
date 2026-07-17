"""Protocol layer: wire framing, transport header, CRC, and value encoding.

Confirmed so far (from static analysis of libAmplifiRemoteNdk.so):

* :mod:`firehawk.protocol.crc` -- the CRC-16/CCITT used by the serial link.
* :mod:`firehawk.protocol.transport_header` -- the 8-byte message transport header.

Still to be finalised (see ``docs/protocol.md``): the ``RobustSerialMsgChannel`` serial
frame (sync/length/seq/ack/segmentation) and the ``TypedValue`` payload encoding for a
"set edit-buffer parameter" message.  Those land in a ``frame.py`` module once the
Ghidra deep-dive and a hardware capture pin down the exact bytes.
"""

from .crc import crc16_ccitt_false, crc16_process, crc16_xmodem
from .frame import Frame, build_control_frame, parse_frame
from .message import (
    KEY_SECTION_ID,
    KEY_SECTION_PARAM,
    KEY_SLOT_ID,
    TVType,
    encode_key_value,
    encode_param,
    encode_typed_value,
)
from .tonematch import (
    Cmd,
    command,
    load_dsp_model,
    set_dsp_model_param,
    set_global_tempo,
    set_preset_pskey_param,
)
from .transport_header import TransportHeader

__all__ = [
    "crc16_process", "crc16_xmodem", "crc16_ccitt_false",
    "TransportHeader",
    "Frame", "build_control_frame", "parse_frame",
    "TVType", "encode_typed_value", "encode_key_value", "encode_param",
    "KEY_SECTION_ID", "KEY_SECTION_PARAM", "KEY_SLOT_ID",
    "Cmd", "command", "set_dsp_model_param", "set_preset_pskey_param",
    "set_global_tempo", "load_dsp_model",
]
