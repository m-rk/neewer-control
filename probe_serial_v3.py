#!/usr/bin/env python3
"""
Serial probe v3 — corrected 8-byte frame format.

Key insight: fs_usage shows the Neewer app sends exactly 8-byte writes to the
serial port. Status packets from the light are also 8 bytes:

    3a 02 03 01 XX YY 00 CS

Where CS = sum(preceding 7 bytes) & 0xFF. The length field is 0x03 but there
are 4 bytes between it and the checksum — the trailing 0x00 is structural.

Previous probes NEVER sent this exact format. build_cmd produced either:
  - 7 bytes (no trailing 0x00)
  - 8 bytes with length=0x04 (wrong length field)

This probe tries the CORRECT 8-byte format: 3a TT 03 PP PP PP 00 CS
"""

import glob
import sys
import time

import serial


def find_serial_port() -> str:
    candidates = glob.glob("/dev/cu.usbserial-*")
    if not candidates:
        print("ERROR: No serial port found")
        sys.exit(1)
    return candidates[0]


def build_frame_8(tag: int, p1: int, p2: int, p3: int) -> bytes:
    """Build an 8-byte frame matching the status packet structure.
    Format: 3a [tag] 03 [p1] [p2] [p3] 00 [checksum]
    """
    frame = bytes([0x3A, tag, 0x03, p1, p2, p3, 0x00])
    cs = sum(frame) & 0xFF
    return frame + bytes([cs])


def build_frame_raw(data: bytes) -> bytes:
    """Build frame from raw bytes (no prefix), adding 0x3a prefix and checksum."""
    frame = bytes([0x3A]) + data
    cs = sum(frame) & 0xFF
    return frame + bytes([cs])


def send_and_listen(ser: serial.Serial, label: str, cmd: bytes, wait: float = 1.0):
    hex_str = cmd.hex(" ")
    print(f"  >> {label:<50s}  [{hex_str}]")
    ser.write(cmd)
    ser.flush()
    time.sleep(0.1)
    start = time.time()
    got_response = False
    while time.time() - start < wait:
        data = ser.read(64)
        if data:
            got_response = True
            print(f"  << RESPONSE ({len(data)} bytes): [{data.hex(' ')}]")
        time.sleep(0.05)
    return got_response


def drain(ser: serial.Serial, timeout: float = 0.5):
    count = 0
    start = time.time()
    while time.time() - start < timeout:
        data = ser.read(256)
        if data:
            count += len(data)
        time.sleep(0.05)
    if count:
        print(f"  (drained {count} bytes)")


def main():
    port = find_serial_port()
    print(f"Neewer PL81-Pro Serial Probe v3 — Corrected 8-byte Format")
    print(f"Device: {port}")
    print()
    print("IMPORTANT: Close the NEEWER Control Center app first!")
    print()

    ser = serial.Serial(
        port=port,
        baudrate=115200,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0,
        write_timeout=1,
        dsrdtr=False,
        rtscts=False,
    )
    ser.dtr = True
    ser.rts = True
    time.sleep(0.3)
    ser.reset_input_buffer()
    drain(ser)

    # =================================================================
    # ROUND 1: Mirror of status format with tag=0x01
    # Status: 3a 02 03 [mode] [bri] [cct] 00 CS
    # Command: 3a 01 03 [mode] [bri] [cct] 00 CS
    # =================================================================
    print("=" * 60)
    print("  ROUND 1: Tag 0x01 (mirror of status tag 0x02)")
    print("  Format: 3a 01 03 [mode] [bri] [cct] 00 [CS]")
    print("=" * 60)

    # CCT mode (mode=0x01), set brightness to max (100=0x64), CCT=0x09
    send_and_listen(ser, "CCT 100% cct=0x09 (7000K?)", build_frame_8(0x01, 0x01, 0x64, 0x09))
    send_and_listen(ser, "CCT 10%  cct=0x09",          build_frame_8(0x01, 0x01, 0x0A, 0x09))
    send_and_listen(ser, "CCT 100% cct=0x20 (3200K?)", build_frame_8(0x01, 0x01, 0x64, 0x20))
    send_and_listen(ser, "CCT 10%  cct=0x20",          build_frame_8(0x01, 0x01, 0x0A, 0x20))
    # Try different mode bytes
    send_and_listen(ser, "mode=0x00 bri=100 cct=0x09",  build_frame_8(0x01, 0x00, 0x64, 0x09))
    send_and_listen(ser, "mode=0x02 bri=100 cct=0x09",  build_frame_8(0x01, 0x02, 0x64, 0x09))

    input("\n  Any reaction? Enter to continue...\n")

    # =================================================================
    # ROUND 2: Try various tags with the 8-byte format
    # =================================================================
    print("=" * 60)
    print("  ROUND 2: Various tags, 8-byte format")
    print("  Format: 3a [tag] 03 01 [bri] 09 00 [CS]")
    print("=" * 60)

    for tag in [0x00, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88]:
        send_and_listen(ser, f"tag=0x{tag:02x} bri=100", build_frame_8(tag, 0x01, 0x64, 0x09), wait=0.3)
        send_and_listen(ser, f"tag=0x{tag:02x} bri=10",  build_frame_8(tag, 0x01, 0x0A, 0x09), wait=0.3)

    input("\n  Any reaction? Enter to continue...\n")

    # =================================================================
    # ROUND 3: BLE-style commands adapted to 8-byte serial format
    # BLE CCT: 78 87 02 [bri] [cct] [CS] = 6 bytes
    # Serial:  3a 87 02 [bri] [cct] 00 00 [CS] = 8 bytes?
    # Or:      3a 87 04 [bri] [cct] 00 00 [CS] = 8 bytes?
    # =================================================================
    print("=" * 60)
    print("  ROUND 3: BLE commands padded to 8 bytes")
    print("=" * 60)

    # BLE CCT command adapted - various padding strategies
    for bri in [0x64, 0x0A]:
        label = f"bri={bri}"
        # Strategy A: tag=87, len=02, then bri,cct,00,00
        frame = bytes([0x3A, 0x87, 0x02, bri, 0x2C, 0x00, 0x00])
        send_and_listen(ser, f"87 len=02 {label} pad=0000", frame + bytes([sum(frame)&0xFF]), wait=0.3)
        # Strategy B: tag=87, len=04, then bri,cct,00,00
        frame = bytes([0x3A, 0x87, 0x04, bri, 0x2C, 0x00, 0x00])
        send_and_listen(ser, f"87 len=04 {label} pad=0000", frame + bytes([sum(frame)&0xFF]), wait=0.3)
        # Strategy C: tag=87, len=02, bri,cct + 0x00 pad + checksum (7 bytes)
        frame = bytes([0x3A, 0x87, 0x02, bri, 0x2C])
        send_and_listen(ser, f"87 len=02 {label} (7 byte)", frame + bytes([sum(frame)&0xFF]), wait=0.3)

    # BLE Power commands adapted to 8 bytes
    # BLE: 78 81 01 01 CS = 5 bytes → serial 8: 3a 81 01 01 00 00 00 CS?
    for power, plabel in [(0x01, "ON"), (0x02, "OFF")]:
        frame = bytes([0x3A, 0x81, 0x01, power, 0x00, 0x00, 0x00])
        send_and_listen(ser, f"Power {plabel} (81 len=01 pad=000000)", frame + bytes([sum(frame)&0xFF]), wait=0.3)
        frame = bytes([0x3A, 0x81, 0x04, power, 0x00, 0x00, 0x00])
        send_and_listen(ser, f"Power {plabel} (81 len=04)", frame + bytes([sum(frame)&0xFF]), wait=0.3)

    input("\n  Any reaction? Enter to continue...\n")

    # =================================================================
    # ROUND 4: Try the EXACT 7-byte BLE format but with 0x3a prefix
    # Maybe commands aren't 8 bytes — maybe the app sends 8 bytes but
    # some are framing/padding that the serial layer adds
    # =================================================================
    print("=" * 60)
    print("  ROUND 4: Exact BLE format with 0x3A prefix (various sizes)")
    print("=" * 60)

    # 5-byte: power
    for power, plabel in [(0x01, "ON"), (0x02, "OFF")]:
        frame = bytes([0x3A, 0x81, 0x01, power])
        send_and_listen(ser, f"Power {plabel} (5B: 3a 81 01 XX CS)", frame + bytes([sum(frame)&0xFF]), wait=0.3)

    # 6-byte: CCT
    for bri in [0x64, 0x0A]:
        frame = bytes([0x3A, 0x87, 0x02, bri, 0x2C])
        send_and_listen(ser, f"CCT bri={bri} cct=0x2C (6B)", frame + bytes([sum(frame)&0xFF]), wait=0.3)
        frame = bytes([0x3A, 0x87, 0x02, bri, 0x09])
        send_and_listen(ser, f"CCT bri={bri} cct=0x09 (6B)", frame + bytes([sum(frame)&0xFF]), wait=0.3)

    input("\n  Any reaction? Enter to continue...\n")

    # =================================================================
    # ROUND 5: Handshake/init + commands
    # The app may send an init command first. Try discovery/info requests
    # then follow with control commands.
    # =================================================================
    print("=" * 60)
    print("  ROUND 5: Initialization + control sequence")
    print("=" * 60)

    # Possible init/info request commands
    init_cmds = [
        ("Init: tag=0x00 (get info?)",     build_frame_8(0x00, 0x00, 0x00, 0x00)),
        ("Init: tag=0x85 (device info?)",   build_frame_8(0x85, 0x00, 0x00, 0x00)),
        ("Init: tag=0x80",                  build_frame_8(0x80, 0x00, 0x00, 0x00)),
        ("Init: tag=0x10",                  build_frame_8(0x10, 0x00, 0x00, 0x00)),
        ("Init: tag=0xFF",                  build_frame_8(0xFF, 0x00, 0x00, 0x00)),
    ]

    for label, cmd in init_cmds:
        resp = send_and_listen(ser, label, cmd, wait=0.5)
        if resp:
            print("  *** GOT A RESPONSE TO INIT! ***")
            # Now try control
            send_and_listen(ser, "Follow-up: CCT 100%", build_frame_8(0x01, 0x01, 0x64, 0x09))
            send_and_listen(ser, "Follow-up: CCT 10%",  build_frame_8(0x01, 0x01, 0x0A, 0x09))

    input("\n  Any reaction? Enter to continue...\n")

    # =================================================================
    # ROUND 6: What if it's NOT 0x3A prefix for commands?
    # Status uses 0x3A, but maybe commands use a different prefix
    # Try the 8-byte format with other prefixes
    # =================================================================
    print("=" * 60)
    print("  ROUND 6: Different prefixes, 8-byte format")
    print("=" * 60)

    for prefix in [0x78, 0x55, 0xAA, 0xA5, 0x5A, 0x80, 0x7E, 0xFE, 0x3B, 0x4A]:
        frame = bytes([prefix, 0x87, 0x02, 0x64, 0x2C, 0x00, 0x00])
        cs = sum(frame) & 0xFF
        cmd = frame + bytes([cs])
        send_and_listen(ser, f"prefix=0x{prefix:02x} CCT 100%", cmd, wait=0.3)
        frame = bytes([prefix, 0x87, 0x02, 0x0A, 0x2C, 0x00, 0x00])
        cs = sum(frame) & 0xFF
        cmd = frame + bytes([cs])
        send_and_listen(ser, f"prefix=0x{prefix:02x} CCT 10%", cmd, wait=0.3)

    input("\n  Any reaction? Enter to continue...\n")

    # =================================================================
    # ROUND 7: What if there's no length byte at all?
    # Maybe: 3a [tag] [p1] [p2] [p3] [p4] [p5] [CS]
    # =================================================================
    print("=" * 60)
    print("  ROUND 7: No length byte — tag + 5 payload bytes + CS")
    print("=" * 60)

    # Possible structures:
    # 3a [subcmd] [mode] [bri] [cct] [??] [??] [CS]
    for tag in [0x01, 0x02, 0x03, 0x87, 0x81]:
        # CCT 100% 7000K
        frame = bytes([0x3A, tag, 0x01, 0x64, 0x09, 0x00, 0x00])
        send_and_listen(ser, f"no-len tag=0x{tag:02x} 01 64 09 00 00", frame + bytes([sum(frame)&0xFF]), wait=0.3)
        # CCT 10%
        frame = bytes([0x3A, tag, 0x01, 0x0A, 0x09, 0x00, 0x00])
        send_and_listen(ser, f"no-len tag=0x{tag:02x} 01 0A 09 00 00", frame + bytes([sum(frame)&0xFF]), wait=0.3)

    ser.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
