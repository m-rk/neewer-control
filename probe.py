#!/usr/bin/env python3
"""
Probe the Neewer PL81-Pro over USB serial using the discovered 0x3A protocol.

Based on captured traffic, the USB protocol uses:
  - Prefix: 0x3A (not 0x78 like BLE)
  - Checksum: sum(all preceding bytes) & 0xFF
  - Baud: 115200, 8N1

This script tries sending commands using 0x3A prefix with both the known
BLE command tags and guessed USB-specific tags. Watch the light for changes.
"""

import glob
import sys
import time

import serial


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_cmd(prefix: int, tag: int, payload: bytes) -> bytes:
    """Build a command: <prefix> <tag> <len> <payload...> <checksum>"""
    frame = bytes([prefix, tag, len(payload)]) + payload
    return frame + bytes([checksum(frame)])


def find_serial_port() -> str:
    candidates = glob.glob("/dev/cu.usbserial-*")
    if not candidates:
        print("ERROR: No /dev/cu.usbserial-* found. Is the light plugged in?")
        sys.exit(1)
    return candidates[0]


def send_and_listen(ser: serial.Serial, label: str, cmd: bytes, wait: float = 1.5):
    """Send a command, print it, and listen for any response."""
    hex_str = cmd.hex(" ")
    print(f"  >> {label:<35s}  [{hex_str}]")
    ser.write(cmd)
    ser.flush()

    # Listen for response
    time.sleep(0.1)
    start = time.time()
    while time.time() - start < wait:
        data = ser.read(256)
        if data:
            print(f"  << RESPONSE ({len(data)} bytes): [{data.hex(' ')}]")
        else:
            time.sleep(0.05)


def main():
    port = find_serial_port()
    print(f"Neewer PL81-Pro Protocol Probe v2")
    print(f"Device: {port}")
    print(f"Baud: 115200")
    print()

    ser = serial.Serial(
        port=port, baudrate=115200,
        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE, timeout=0, write_timeout=1,
    )
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    # First, drain any unsolicited status packets from the light
    print("Draining unsolicited data for 2 seconds...")
    start = time.time()
    while time.time() - start < 2:
        data = ser.read(256)
        if data:
            print(f"  << UNSOLICITED: [{data.hex(' ')}]")
        time.sleep(0.05)
    print()

    # --- Round 1: 0x3A prefix with BLE command tags ---
    print("=" * 60)
    print("  ROUND 1: 0x3A prefix + BLE command tags")
    print("=" * 60)

    tests_3a_ble = [
        ("Power ON  (3A 81)",    build_cmd(0x3A, 0x81, bytes([0x01]))),
        ("Power OFF (3A 81)",    build_cmd(0x3A, 0x81, bytes([0x02]))),
        ("CCT 50% 5000K (3A 87)", build_cmd(0x3A, 0x87, bytes([0x32, 0x2C]))),
        ("CCT 100% (3A 87)",     build_cmd(0x3A, 0x87, bytes([0x64, 0x2C]))),
        ("CCT 10% (3A 87)",      build_cmd(0x3A, 0x87, bytes([0x0A, 0x2C]))),
        ("RGB Red (3A 86)",      build_cmd(0x3A, 0x86, bytes([0x00, 0x00, 0x64, 0x64]))),
        ("RGB Green (3A 86)",    build_cmd(0x3A, 0x86, bytes([0x78, 0x00, 0x64, 0x64]))),
        ("RGB Blue (3A 86)",     build_cmd(0x3A, 0x86, bytes([0xF0, 0x00, 0x64, 0x64]))),
    ]

    for label, cmd in tests_3a_ble:
        send_and_listen(ser, label, cmd)

    input("\nDid anything happen? Press Enter to continue...\n")

    # --- Round 2: 0x3A prefix with status-report-style tags ---
    # The light sends 0x3A 0x02 for status. Maybe commands use 0x01?
    print("=" * 60)
    print("  ROUND 2: 0x3A prefix + guessed command tags")
    print("=" * 60)

    tests_3a_guess = [
        # Tag 0x01 — maybe "set state" (inverse of 0x02 "report state")
        ("Set CCT 100% (tag 01)", build_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09]))),
        ("Set CCT 10%  (tag 01)", build_cmd(0x3A, 0x01, bytes([0x01, 0x0A, 0x09]))),
        ("Set CCT 50%  (tag 01)", build_cmd(0x3A, 0x01, bytes([0x01, 0x32, 0x09]))),

        # Try with extra trailing 0x00 like the status packets have
        ("Set CCT 100% +00 (tag 01)", build_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09, 0x00]))),
        ("Set CCT 10%  +00 (tag 01)", build_cmd(0x3A, 0x01, bytes([0x01, 0x0A, 0x09, 0x00]))),

        # Maybe tag 0x03 or 0x04?
        ("Set CCT 100% (tag 03)", build_cmd(0x3A, 0x03, bytes([0x01, 0x64, 0x09]))),
        ("Set CCT 100% (tag 04)", build_cmd(0x3A, 0x04, bytes([0x01, 0x64, 0x09]))),
        ("Set CCT 100% (tag 05)", build_cmd(0x3A, 0x05, bytes([0x01, 0x64, 0x09]))),
    ]

    for label, cmd in tests_3a_guess:
        send_and_listen(ser, label, cmd)

    input("\nDid anything happen? Press Enter to continue...\n")

    # --- Round 3: Raw BLE commands unchanged (0x78 prefix) at 115200 ---
    # Maybe the light accepts both prefixes?
    print("=" * 60)
    print("  ROUND 3: Original BLE commands (0x78) at 115200 baud")
    print("=" * 60)

    tests_78 = [
        ("Power ON  (78 81)", build_cmd(0x78, 0x81, bytes([0x01]))),
        ("Power OFF (78 81)", build_cmd(0x78, 0x81, bytes([0x02]))),
        ("CCT 100% (78 87)",  build_cmd(0x78, 0x87, bytes([0x64, 0x2C]))),
        ("CCT 10%  (78 87)",  build_cmd(0x78, 0x87, bytes([0x0A, 0x2C]))),
    ]

    for label, cmd in tests_78:
        send_and_listen(ser, label, cmd)

    input("\nDid anything happen? Press Enter to continue...\n")

    # --- Round 4: Mirror the exact status packet format back as a command ---
    # What if we just echo the status format but with different values?
    print("=" * 60)
    print("  ROUND 4: Echo status packet format as commands")
    print("=" * 60)

    tests_echo = [
        # Exact format: 3a 02 03 [mode] [brightness] [cct] [00] [checksum]
        ("Echo brightness=100", build_cmd(0x3A, 0x02, bytes([0x01, 0x64, 0x09, 0x00]))),
        ("Echo brightness=5",   build_cmd(0x3A, 0x02, bytes([0x01, 0x05, 0x09, 0x00]))),
        ("Echo brightness=50",  build_cmd(0x3A, 0x02, bytes([0x01, 0x32, 0x09, 0x00]))),
        ("Echo cct=0x20",       build_cmd(0x3A, 0x02, bytes([0x01, 0x32, 0x20, 0x00]))),
        ("Echo cct=0x38",       build_cmd(0x3A, 0x02, bytes([0x01, 0x32, 0x38, 0x00]))),
    ]

    for label, cmd in tests_echo:
        send_and_listen(ser, label, cmd)

    input("\nDid anything happen? Press Enter to continue...\n")

    # --- Round 5: Try simple single-byte and two-byte commands ---
    print("=" * 60)
    print("  ROUND 5: Minimal / exploratory commands")
    print("=" * 60)

    tests_minimal = [
        # Maybe just the prefix + a simple byte?
        ("Just 3A",              bytes([0x3A])),
        ("3A 00",                bytes([0x3A, 0x00])),
        ("3A 01",                bytes([0x3A, 0x01])),
        ("3A 02",                bytes([0x3A, 0x02])),
        # Try newline-terminated (some serial protocols use text)
        ("TEXT: ON\\r\\n",       b"ON\r\n"),
        ("TEXT: on\\r\\n",       b"on\r\n"),
        # Try the NeewerLite-Python "new style" with MAC-addressed format
        ("3A 8D power on",       build_cmd(0x3A, 0x8D, bytes([0x00]*6 + [0x81, 0x01]))),
        ("3A 8E CCT",           build_cmd(0x3A, 0x8E, bytes([0x00]*6 + [0x87, 0x64, 0x2C]))),
    ]

    for label, cmd in tests_minimal:
        hex_str = cmd.hex(" ")
        print(f"  >> {label:<35s}  [{hex_str}]")
        ser.write(cmd)
        ser.flush()
        time.sleep(0.1)
        data = ser.read(256)
        if data:
            print(f"  << RESPONSE ({len(data)} bytes): [{data.hex(' ')}]")
        time.sleep(1.0)

    ser.close()
    print()
    print("Done. If nothing worked, we need to sniff the Neewer app traffic")
    print("through the proxy (run sniff.py and connect the app to the PTY).")


if __name__ == "__main__":
    main()
