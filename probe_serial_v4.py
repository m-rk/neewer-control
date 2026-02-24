#!/usr/bin/env python3
"""
Neewer PL81-Pro — Serial probe with 16-bit USB checksum.

NEW THEORY: Commands go through serial, not HID.
  - HID (Realtek) = hub management only (stays when light unplugged)
  - Serial (CH340) = actual light control
  - App's fs_usage showed 8-byte serial writes
  - Binary's checkSumWithUsbData: uses 16-bit big-endian checksum
  - We never tried 16-bit checksums on serial — only 1-byte!

Command format: [0x3A] [tag] [payload_len] [payload...] [cs_hi] [cs_lo]
  Power on:   3A 06 01 01 [cs_hi] [cs_lo]  (6 bytes)
  Power off:  3A 06 01 02 [cs_hi] [cs_lo]  (6 bytes)
  CCT:        3A 02 03 01 [bri] [temp] [cs_hi] [cs_lo]  (8 bytes)

RUN FROM GHOSTTY:
    python3 probe_serial_v4.py
"""

import serial
import glob
import sys
import time


def usb_checksum_16bit(data: bytes) -> bytes:
    """16-bit big-endian sum (from binary disassembly)."""
    s = sum(data) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


def ble_checksum_8bit(data: bytes) -> bytes:
    """1-byte sum (standard BLE/serial)."""
    return bytes([sum(data) & 0xFF])


def build_16bit(payload: bytes) -> bytes:
    return payload + usb_checksum_16bit(payload)


def build_8bit(payload: bytes) -> bytes:
    return payload + ble_checksum_8bit(payload)


def try_serial_cmd(ser, data, label, wait=1.0):
    hex_str = data.hex(" ")
    ser.reset_input_buffer()
    ser.write(data)
    ser.flush()
    time.sleep(wait)
    response = ser.read(ser.in_waiting or 0)
    resp_str = response.hex(" ") if response else "(none)"
    print(f"  {label:<55s} [{hex_str}] resp={resp_str}")
    return len(response) > 0


def main():
    print("=" * 70)
    print("  Neewer PL81-Pro — Serial probe with 16-bit checksum")
    print("  Theory: commands go via serial, NOT HID")
    print("=" * 70)
    print()

    ports = glob.glob("/dev/cu.usbserial-*")
    if not ports:
        print("No serial port found!")
        sys.exit(1)

    port = ports[0]
    print(f"Using: {port}")
    ser = serial.Serial(port, 115200, timeout=1)
    time.sleep(0.5)

    # Drain any pending status data
    pending = ser.read(ser.in_waiting or 0)
    if pending:
        print(f"Drained: {pending.hex(' ')}")
    print()

    any_response = False

    # ================================================================
    # ROUND 1: Commands with 16-bit big-endian checksum (from binary)
    # ================================================================
    print("--- Round 1: 16-bit checksum (decoded from app binary) ---")

    cmds = [
        ("Power ON",           build_16bit(bytes([0x3A, 0x06, 0x01, 0x01]))),
        ("Power OFF",          build_16bit(bytes([0x3A, 0x06, 0x01, 0x02]))),
        ("CCT 100% 7000K",     build_16bit(bytes([0x3A, 0x02, 0x03, 0x01, 0x64, 0x09]))),
        ("CCT 50% 7000K",      build_16bit(bytes([0x3A, 0x02, 0x03, 0x01, 0x32, 0x09]))),
        ("CCT 10% 7000K",      build_16bit(bytes([0x3A, 0x02, 0x03, 0x01, 0x0A, 0x09]))),
        ("TurnOn+CCT 100%",    build_16bit(bytes([0x3A, 0x02, 0x03, 0x01, 0x64, 0x09]))),
    ]

    for label, cmd in cmds:
        ok = try_serial_cmd(ser, cmd, label)
        if ok:
            any_response = True

    print()

    # ================================================================
    # ROUND 2: Same commands with 1-byte checksum (what we tried before)
    # ================================================================
    print("--- Round 2: 1-byte checksum (serial status format) ---")

    cmds2 = [
        ("Power ON (1-byte cs)",   build_8bit(bytes([0x3A, 0x06, 0x01, 0x01]))),
        ("CCT 100% (1-byte cs)",   build_8bit(bytes([0x3A, 0x02, 0x03, 0x01, 0x64, 0x09]))),
    ]

    for label, cmd in cmds2:
        ok = try_serial_cmd(ser, cmd, label)
        if ok:
            any_response = True

    print()

    # ================================================================
    # ROUND 3: Status format with padding byte (as received from light)
    # Light sends: 3A 02 03 01 [bri] [cct] 00 [1-byte cs]
    # Maybe commands need the same format?
    # ================================================================
    print("--- Round 3: Exact status format (with 0x00 pad + 1-byte cs) ---")

    for bri in [0x64, 0x0A]:
        payload = bytes([0x3A, 0x02, 0x03, 0x01, bri, 0x09, 0x00])
        cmd = payload + ble_checksum_8bit(payload)
        try_serial_cmd(ser, cmd, f"Status fmt bri={bri:#04x} (8 bytes)")

    print()

    # ================================================================
    # ROUND 4: 16-bit checksum with different tags
    # Maybe the serial command tag differs from the HID tag
    # ================================================================
    print("--- Round 4: 16-bit checksum, different tags ---")

    for tag in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x81, 0x82, 0x86, 0x87, 0x88]:
        cmd = build_16bit(bytes([0x3A, tag, 0x03, 0x01, 0x64, 0x09]))
        try_serial_cmd(ser, cmd, f"Tag 0x{tag:02x}: 3A {tag:02x} 03 01 64 09 + 16cs", wait=0.3)

    print()

    # ================================================================
    # ROUND 5: Try without 0x3A prefix (maybe it's just the checksum)
    # ================================================================
    print("--- Round 5: No 0x3A prefix ---")

    cmd = build_16bit(bytes([0x02, 0x03, 0x01, 0x64, 0x09]))
    try_serial_cmd(ser, cmd, "02 03 01 64 09 + 16cs (no 3A)")

    cmd = build_16bit(bytes([0x06, 0x01, 0x01]))
    try_serial_cmd(ser, cmd, "06 01 01 + 16cs (no 3A)")

    print()

    # ================================================================
    # ROUND 6: BLE commands over serial with 16-bit checksum
    # ================================================================
    print("--- Round 6: BLE commands + 16-bit checksum ---")

    cmds6 = [
        ("BLE Power ON + 16cs",  build_16bit(bytes([0x78, 0x81, 0x01, 0x01]))),
        ("BLE CCT 100% + 16cs",  build_16bit(bytes([0x78, 0x87, 0x02, 0x64, 0x2C]))),
        ("BLE Power ON + 8cs",   build_8bit(bytes([0x78, 0x81, 0x01, 0x01]))),
        ("BLE CCT 100% + 8cs",   build_8bit(bytes([0x78, 0x87, 0x02, 0x64, 0x2C]))),
    ]

    for label, cmd in cmds6:
        ok = try_serial_cmd(ser, cmd, label, wait=0.5)
        if ok:
            any_response = True

    print()

    # ================================================================
    # ROUND 7: Write command then immediately read status
    # Maybe the light responds with a status packet after a valid command
    # ================================================================
    print("--- Round 7: Write + extended read (3 second wait) ---")

    cmd = build_16bit(bytes([0x3A, 0x06, 0x01, 0x01]))
    ser.reset_input_buffer()
    ser.write(cmd)
    ser.flush()
    print(f"  Sent: {cmd.hex(' ')}")
    print(f"  Waiting 3 seconds for any response...")
    time.sleep(3)
    response = ser.read(ser.in_waiting or 0)
    if response:
        print(f"  Response: {response.hex(' ')}")
        any_response = True
    else:
        print(f"  No response")

    print()

    # ================================================================
    # ROUND 8: Try with DTR/RTS toggling (handshake signals)
    # ================================================================
    print("--- Round 8: DTR/RTS toggling + command ---")

    for dtr, rts in [(True, True), (True, False), (False, True), (False, False)]:
        ser.dtr = dtr
        ser.rts = rts
        time.sleep(0.1)
        cmd = build_16bit(bytes([0x3A, 0x06, 0x01, 0x01]))
        ser.reset_input_buffer()
        ser.write(cmd)
        ser.flush()
        time.sleep(0.5)
        response = ser.read(ser.in_waiting or 0)
        resp_str = response.hex(" ") if response else "(none)"
        print(f"  DTR={dtr} RTS={rts}: Power ON -> resp={resp_str}")
        if response:
            any_response = True

    print()

    if any_response:
        print("*** Got a response! ***")
    else:
        print("No responses from any serial command.")
        print()
        print("Remaining possibilities:")
        print("  1. The app may use IOKit serial (not /dev/) with different settings")
        print("  2. Commands might need the serial port opened in a specific mode")
        print("  3. The light might only accept commands when both serial + HID")
        print("     are open simultaneously (dual-channel handshake)")

    ser.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
