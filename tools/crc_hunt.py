#!/usr/bin/env python3
"""
crc_hunt.py - Identify the CRC-16 variant and checksummed span from captured frame(s).

Contributed by Claudia (Web Chat Opus). Kept as a capture-side cross-check: when we
get a real captured frame for a known action, this confirms — against actual bytes —
what static analysis already read out of the pedal's CRC16_Process.

What Ghidra already established (see ../docs/protocol.md), for reference:
  * The CRC is **CRC-16/CCITT-FALSE** (poly 0x1021, init 0xFFFF, non-reflected).
  * The serial frame is length-prefixed, NOT HDLC — sync 0x55 0x55, then a 12-byte
    header, then the payload. There is no 0x7E/0x7D byte-stuffing, so feed captured
    bytes to this tool RAW (no un-escaping needed).
  * FreedomHawk wrinkle: the header CRC (frame bytes 10-11) is computed over the whole
    12-byte header with those 2 CRC bytes treated as zero. So for a 12-byte control
    frame, the checksummed region is bytes[0:12] with bytes[10:12]=0 — slightly
    different from this tool's "everything before the trailing 2 bytes" assumption.
    Use this tool to confirm the *variant*; use docs/protocol.md for the exact spans.

Usage:
    python crc_hunt.py "aa 02 11 00 3e 82 ...."      # one frame, hex (spaces optional)
    python crc_hunt.py frame1.hex frame2.hex          # files, one hex frame each

Give it a full frame INCLUDING the trailing 2-byte CRC. It tries every standard
CRC-16 definition over every plausible (start, end) span and reports which
combination reproduces the trailing bytes. Run it on 2-3 frames; the real answer
is the (variant, span-rule) that holds for ALL of them.
"""
import sys


# General parametric CRC-16 (bit-by-bit; clear over fast, this is a one-shot tool).
def crc16(data, poly, init, refin, refout, xorout):
    def rev(x, n):
        r = 0
        for _ in range(n):
            r = (r << 1) | (x & 1); x >>= 1
        return r
    crc = init
    for b in data:
        if refin:
            b = rev(b, 8)
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xffff if (crc & 0x8000) else (crc << 1) & 0xffff
    if refout:
        crc = rev(crc, 16)
    return crc ^ xorout


# Standard catalog: name -> (poly, init, refin, refout, xorout)
CATALOG = {
    "CRC-16/CCITT-FALSE": (0x1021, 0xFFFF, False, False, 0x0000),
    "CRC-16/XMODEM":      (0x1021, 0x0000, False, False, 0x0000),
    "CRC-16/KERMIT":      (0x1021, 0x0000, True,  True,  0x0000),
    "CRC-16/CCITT(0x1D0F)": (0x1021, 0x1D0F, False, False, 0x0000),
    "CRC-16/GENIBUS":     (0x1021, 0xFFFF, False, False, 0xFFFF),
    "CRC-16/MCRF4XX":     (0x1021, 0xFFFF, True,  True,  0x0000),
    "CRC-16/X25":         (0x1021, 0xFFFF, True,  True,  0xFFFF),
    "CRC-16/ARC(IBM)":    (0x8005, 0x0000, True,  True,  0x0000),
    "CRC-16/MODBUS":      (0x8005, 0xFFFF, True,  True,  0x0000),
    "CRC-16/USB":         (0x8005, 0xFFFF, True,  True,  0xFFFF),
    "CRC-16/MAXIM":       (0x8005, 0x0000, True,  True,  0xFFFF),
    "CRC-16/BUYPASS":     (0x8005, 0x0000, False, False, 0x0000),
    "CRC-16/DDS-110":     (0x8005, 0x800D, False, False, 0x0000),
    "CRC-16/DECT-R":      (0x0589, 0x0000, False, False, 0x0001),
    "CRC-16/EN13757":     (0x3D65, 0x0000, False, False, 0xFFFF),
    "CRC-16/T10-DIF":     (0x8BB7, 0x0000, False, False, 0x0000),
    "CRC-16/CDMA2000":    (0xC867, 0xFFFF, False, False, 0x0000),
}


def parse_hex(s):
    s = s.replace("0x", "").replace(",", " ")
    if " " in s.strip():
        return bytes(int(t, 16) for t in s.split())
    return bytes.fromhex(s.strip())


def analyze(frame):
    n = len(frame)
    trailer_le = frame[-2] | (frame[-1] << 8)     # CRC stored little-endian
    trailer_be = (frame[-2] << 8) | frame[-1]     # CRC stored big-endian
    hits = []
    # try every start offset (skip leading sync/header bytes) up to the trailer
    for start in range(0, n - 2):
        body = frame[start:n - 2]
        if not body:
            continue
        for name, (poly, init, rin, rout, xor) in CATALOG.items():
            c = crc16(body, poly, init, rin, rout, xor)
            if c == trailer_le:
                hits.append((name, start, n - 2, "LE"))
            if c == trailer_be:
                hits.append((name, start, n - 2, "BE"))
    return hits


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    frames = []
    for a in args:
        try:
            with open(a) as f:
                frames.append(parse_hex(f.read()))
        except OSError:
            frames.append(parse_hex(a))
    per = [set(analyze(fr)) for fr in frames]
    for i, (fr, h) in enumerate(zip(frames, per)):
        print(f"frame {i} ({len(fr)} bytes): {len(h)} candidate(s)")
        for name, s, e, endian in sorted(h):
            print(f"    {name:22} span[{s}:{e}] crc-{endian}")
    if len(per) > 1:
        common = set.intersection(*per)
        print(f"\nCONSISTENT across all {len(per)} frames: "
              + (", ".join(f'{n} span[{s}:{e}] {en}' for n, s, e, en in sorted(common))
                 or "NONE — check frame boundaries"))


if __name__ == "__main__":
    main()
