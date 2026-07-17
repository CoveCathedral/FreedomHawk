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
non-reflected. **CONFIRMED (from `RobustSerialMsgChannel_ExecTasks`/`HandleRxData`): the init
is `0xFFFF`** — i.e. **CRC-16/CCITT-FALSE**. Both the header CRC and the payload CRC seed
with `0xFFFF`. See the frame layout below for the exact spans.

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

## CONFIRMED: Serial frame framing (`RobustSerialMsgChannel_ExecTasks` / `_HandleRxData`)

Decompiled (Ghidra). Every frame starts with a 12-byte header; a data frame is followed by
its payload. All multi-byte fields little-endian.

```
byte  0-1   sync       = 0x55 0x55
byte  2     (flags)    = 0x00 in observed builder path
byte  3     seq        sender sequence number (reliable channel)
byte  4     (window)   channel window/rx index (param+0x16)
byte  5     ack        acknowledgement number
byte  6-7   length     payload length in bytes (0 for a control/ack frame)
byte  8-9   payloadCRC CRC-16/CCITT-FALSE (init 0xFFFF) over the payload bytes (0 if none)
byte 10-11  headerCRC  CRC-16/CCITT-FALSE (init 0xFFFF) over bytes 0..11 with 10-11 = 0
byte 12..   payload    `length` bytes (data frames only), sent in 4-byte-aligned segments
```

* **Control/ACK frame** = the 12-byte header alone (`length` = 0, `payloadCRC` = 0).
* **Data frame** = header + payload. Max payload = (max frame size − 12); segments are
  padded up to a 4-byte boundary (`(len + 3) & ~3`).
* RX (`HandleRxData`) is a 3-state machine: scan for `0x5555`, collect the 12-byte header
  and verify `headerCRC`, then read `length` payload bytes verifying `payloadCRC`.

The payload is a **transport header (8 bytes, see above) + the serialized message body**.

**Still to confirm from a capture:** the exact meaning of byte 2 and byte 4, and which
transport-header port address is the edit buffer.

## CONFIRMED: Message body / value encoding (`L6SPePresetSerializer`)

Decompiled. The message body is a stream of **key → value** entries:

```
entry = uint32 key  +  TypedValue
TypedValue = uint16 type  +  value
```

* `SerializeKeyValue(key, tv)` writes the 4-byte key then the TypedValue.
* `SerializeTypedValue(tv)` writes a 2-byte type tag then the value. Primitive types (tag
  0–7) go through a jump table (per-type value layout — the one remaining fine detail);
  strings (`SerializeStringValue`, tag `4`) write `uint16 type=4, uint32 length, bytes`.
* **Structural directive keys** have the high bit set:
  `0x80000000` = section id, `0x80000001` = section param, `0x80000003` = slot id
  (`StoreSectionStart`, `StoreSlotStart`), each with a small-int TypedValue.
* **Parameter entries** (`L6A36Preset::SerializeParameterPSKey`): a numeric **PSKey**
  addresses a (groupID, paramID) pair via `PSKeyToParamIDandGroupID(psKey, &param, &group,
  &valueType)`. The value is written as a `TypedValue` whose value field is the parameter
  value — **continuous params as an IEEE-754 float** (normalised 0.0–1.0), bools as 0.0/1.0,
  ints coerced likewise in this path.

So a "set edit-buffer parameter" reduces to: frame( transportHeader + [ key(4) +
TypedValue(type, float) ] ).

### Parameter addressing — two schemes (from the PSKey table @ vaddr 0x22e9e0)

The static PSKey table `{paramID*, groupID*, psKey, valueType}` decompiled from
`PSKeyToParamIDandGroupID` was located and read out of the binary. It covers the
**structural / control parameters only** — every block's `@enabled`, `@mix`, `@post`,
`@mixtype`, `@stereo`, the block enables, plus `global` (`@tempo`→3, `@tweakmin`→7,
`@tweakmax`→8, `@pedal2assign`→9) and `variax` (`@string1tuning`→0x1c … `@string6tuning`→
0x21). These get a fixed numeric **psKey** (structural keys live in the ~0x1c4c00–0x1c4e90
range; global/variax are small).

The **model knobs** (Bass, Drive, Treble, …) are **not** in this table — they are addressed
through the **symbol table** (`defaultSymbolTable.bin`, already decoded) by symbol index
within the currently selected model.

### IMPORTANT: two distinct write paths (`sendParamToDevice` decompiled)

There are **two different message formats**, and a live single-knob tweak does NOT use the
preset serializer:

1. **Bulk preset / model save** → `L6SPePresetSerializer` key→TypedValue stream (the
   `encode_*` in `message.py`). Used by `savePresetToDevice` / `WriteModelToDevice`.
2. **Live single parameter set** → the **ToneMatch editor** service. `sendParamToDevice`
   dispatches:
   - **model knob** (Bass, Drive): `GetDSPSlotForGroupAndParam(group, param)` →
     `ToneMatchEditorService::setToneMatchModelParam(param, slot, value)` →
     `ToneMatchEdit_Remote::SetDspModelParam(slot, paramId, toneMatchEditorTypedValue)`.
   - **structural param**: `ParamIDToPSKey(param)` →
     `setPresetPSKeyParam(psKey, value)` → `ToneMatchEdit_Remote::SetPresetPSKeyParam`.
   - tempo → `SetGlobalTempo`; footswitch → `setFootswitchAssign`; cab model+mic →
     `setToneMatchModel`; tweak bind → `bindTweak`.

### CONFIRMED: ToneMatch command format (`DoCommandCommon` + callers, implemented)

Every ToneMatch command (built in `DoCommandCommon`, sent as the frame payload) is:

    [uint32 cmdID][uint32 dataLen][data ...]

A ToneMatch typed value is `[uint32 type][uint32 value]` (the value word holds IEEE-754
float bits for a continuous param). The confirmed commands:

| Command                | cmdID  | data |
|------------------------|--------|------|
| `LoadDspModel`         | `0x08` | `[uint32 slot][uint32 modelId]` |
| `SetDspModelParam`     | `0x0A` | `[uint32 slot][uint32 paramId][uint32 type][uint32 value]` |
| `SetGlobalTempo`       | `0x0E` | `[float bpm]` (raw, no type tag) |
| `SetPresetPSKeyParam`  | `0x13` | `[uint32 psKey][uint32 type][uint32 value]` |

For a **model knob**: `GetDSPSlotForGroupAndParam(group, param)` resolves the block to a DSP
`slot` and the param to a symbol; `paramId` is that param's **index in the symbol table**
(`defaultSymbolTable.bin`, already decoded). For a **structural param**: `ParamIDToPSKey`
gives the `psKey` (the table read out above). Implemented in
`firehawk.protocol.tonematch`, with unit tests on the byte layout.

**Remaining (small, capture-confirmable):** the exact `type` enum value for a float typed
value, the DSP `slot` numbering per group, and which transport-header port the ToneMatch
editor uses. The message *structure* is confirmed and coded.
