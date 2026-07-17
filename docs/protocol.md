# Firehawk FX wire protocol — reverse-engineering notes

Status: **in progress.** This document records what is *confirmed* from static analysis
of `libAmplifiRemoteNdk.so` (x86 build) versus what is still open. Confirmed items note
the source function; open items say what's needed to close them.

The full protocol stack, from the native symbol table (`tools/native_protocol_symbols.txt`):

```
L6A36Preset::SerializeToDeviceForGroup / L6SPePresetSerializer   (payload: preset & params)
        v
MsgPort_* / MsgRouter_*  (addressed endpoints: edit buffer, tuner, settings)
        v
MsgTransportHeader_Pack  (8-byte transport header)
        v
RobustSerialMsgChannel_* (reliable framed channel: seq/ack, segmentation, CRC-16)
        v
AndroidSppMsgChannel_write -> SppListener.SppOutStreamData(byte[]) -> RFCOMM socket
```

## CONFIRMED: CRC-16 algorithm (`CRC16_Process` @ 0x103b10)

Exact transcription of the 79-byte function, verified against standard check values:

```python
# CRC-16/CCITT, polynomial 0x1021, NON-reflected, no final xor.
# Init value is seeded by the caller (see framing layer) -> 0x0000 or 0xFFFF, TBD.
def crc16_process(crc, data):
    for b in data:
        x = (b ^ (crc >> 8)) & 0xFF
        y = (x ^ (x >> 4)) & 0xFFFF
        crc = ((crc << 8) ^ (y << 12) ^ (y << 5) ^ y) & 0xFFFF
    return crc
```

`crc16_process(0x0000, b"123456789") == 0x31C3` (XMODEM) and
`crc16_process(0xFFFF, ...) == 0x29B1` (CCITT-FALSE) — both match, confirming poly 0x1021,
non-reflected. **Open:** the initial value and the exact byte span the CRC covers — read
from the `RobustSerialMsgChannel` caller.

## CONFIRMED: Transport header layout (`MsgTransportHeader_Pack` @ 0x1022b0)

In-memory header struct (8 bytes) -> packed as two little-endian uint32 words:

| Packed | Bits | Source (struct offset) | Meaning (tentative) |
|--------|------|------------------------|---------------------|
| word0[31:28] | 4  | byte[0]      | message type / class |
| word0[27:26] | 2  | byte[1] & 3  | constant `2` when built by `MsgPort_PrepareTransportHeader` (addr-type/version) |
| word0[25:16] | 10 | —            | reserved (unused) |
| word0[15:0]  | 16 | word[2]      | field C (message length or id) |
| word1[15:0]  | 16 | word[4]      | field D — port address (from `port+0x14`) |
| word1[31:16] | 16 | word[6]      | field E — port address (from `port+0x16`) |

`MsgPort_PrepareTransportHeader` builds it with: byte0 = caller arg, byte1 = 2 (const),
word@2 = caller arg (length/id), word@4/@6 = the port's two 16-bit addresses (local/remote).
**Open:** which of D/E is source vs destination, and whether field C is length or a message id.

## Device identification (resolved: read at runtime)

Two separate numbering schemes exist:

* **Java layer** identifies the connected unit by *name string* (`Firehawk_FX`,
  `Firehawk_1500`, `AMPLIFI_FX100`, ...) derived from the Bluetooth device name
  (`DeviceConnectionManager.getModelNameFromBluetoothDevice`). `ConnectedLine6Device$Model`
  is a plain `(name, ordinal)` enum (FIREHAWK_FX = ordinal 5) — it carries **no** numeric
  device code.
* **Preset / native layer** uses an internal device-type code (`default_preset.json`
  `device = 2097154 = 0x200002`; HD models restrict to `devices:[2097156, 2097158]` =
  `0x200004`, `0x200006`). These almost certainly are the two Firehawk units (FX + 1500),
  which share the HD amp pack, versus older AMPLIFi hardware at `0x200002`.

**Design decision:** do not hardcode the Firehawk FX device code. Offline, the app offers
every model (`available_on(None) == True`). When connected, read the pedal's own product ID
(`nativeGetProductId` equivalent) and filter models by it. The exact FX code will be
confirmed from the hardware / a capture and recorded here then.

## OPEN: Serial frame framing (`RobustSerialMsgChannel_*`)

The bytes actually written to the socket are produced here (start/sync byte(s), length
field, sequence/ack for the reliable layer, segmentation via `MsgSegmentIter_*`, and the
CRC-16 trailer). To close: read `RobustSerialMsgChannel_QueueOutMessage`,
`RobustSerialMsgChannel_ExecTasks`, `RobustSerialMsgChannel_HandleRxData`, and
`AndroidSppMsgChannel_write`. Cross-check with one Bluetooth HCI capture of a known edit.

## OPEN: Payload encoding (`L6A36Preset` / `L6SPePresetSerializer` / `TypedValue`)

How a (group, param, value) is encoded: params are keyed via a `SymbolTable*` (the decoded
`defaultSymbolTable.bin`), values carried as a tagged `TypedValue` (int/float/string/varray).
`SerializeToDeviceForGroup(SymbolTable*, L6Buffer*, groupName)` serializes a whole group.
To close: read `L6SPePresetSerializer::SerializeTypedValue` and `SerializeParameterPSKey`.
