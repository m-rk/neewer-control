#!/usr/bin/env python3
"""
Neewer PL81-Pro USB Control

Controls the Neewer PL81-Pro LED panel via USB serial (CH340).
Protocol reverse-engineered from the NEEWER Control Center app binary.
PL81-Pro is a bi-color (CCT-only) panel — no RGB/HSI support.

Usage:
    python3 neewer_control.py cct <brightness> [temp_byte_hex]
    python3 neewer_control.py on
    python3 neewer_control.py off
    python3 neewer_control.py status
    python3 neewer_control.py temp-scan

Examples:
    python3 neewer_control.py cct 100       # 100% brightness, keep temp
    python3 neewer_control.py cct 50 09     # 50% brightness, temp=0x09
    python3 neewer_control.py cct 0         # brightness 0 (effectively off)
    python3 neewer_control.py status        # read current state
    python3 neewer_control.py temp-scan     # sweep temp values to map K
"""

import serial
import glob
import sys
import time


def find_serial_port():
    ports = glob.glob("/dev/cu.usbserial-*")
    if not ports:
        print("Error: No USB serial port found. Is the light connected?")
        sys.exit(1)
    return ports[0]


def usb_checksum(data: bytes) -> bytes:
    """16-bit big-endian checksum (decoded from app binary)."""
    s = sum(data) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


def send_command(ser, payload: bytes, wait=0.5) -> bytes:
    """Send command and return response (if any)."""
    cmd = payload + usb_checksum(payload)
    ser.reset_input_buffer()
    ser.write(cmd)
    ser.flush()
    time.sleep(wait)
    n = ser.in_waiting
    if n > 0:
        return ser.read(n)
    return b""


def set_cct(ser, brightness: int, temperature: int = 0x09):
    """Set CCT mode: brightness 0-100, temperature byte."""
    brightness = max(0, min(100, brightness))
    payload = bytes([0x3A, 0x02, 0x03, 0x01, brightness, temperature])
    resp = send_command(ser, payload)
    if resp:
        print(f"OK: brightness={brightness}% temp=0x{temperature:02x}")
    else:
        print(f"Sent (no echo): brightness={brightness}% temp=0x{temperature:02x}")


def read_status(ser, timeout=3.0):
    """Read status packets from the light."""
    print(f"Listening for status packets ({timeout}s)...")
    print("(Turn the knob on the light to trigger a status update)")
    ser.reset_input_buffer()
    end = time.time() + timeout
    while time.time() < end:
        n = ser.in_waiting
        if n >= 8:
            data = ser.read(8)
            if data[0] == 0x3A and data[1] == 0x02:
                bri = data[4]
                temp = data[5]
                print(f"  Status: brightness={bri}% temp=0x{temp:02x} raw={data.hex(' ')}")
        time.sleep(0.1)


def temp_scan(ser):
    """Sweep temperature values to map byte → Kelvin."""
    print("Temperature sweep — watch the light color change")
    print("Format: temp_byte → visual color")
    print()
    for t in range(0x00, 0x40):
        payload = bytes([0x3A, 0x02, 0x03, 0x01, 0x64, t])
        resp = send_command(ser, payload, wait=0.3)
        ack = "echo" if resp else "---"
        print(f"  temp=0x{t:02x} ({t:3d}) [{ack}]")
    print()
    print("Done. Note which values produced visible color changes.")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  neewer_control.py cct <brightness> [temp_hex]")
        print("  neewer_control.py on")
        print("  neewer_control.py off")
        print("  neewer_control.py status")
        print("  neewer_control.py temp-scan")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    port = find_serial_port()
    ser = serial.Serial(port, 115200, timeout=1)
    time.sleep(0.2)
    ser.read(ser.in_waiting or 0)  # drain

    if cmd == "cct":
        if len(sys.argv) < 3:
            print("Usage: neewer_control.py cct <brightness> [temp_hex]")
            sys.exit(1)
        bri = int(sys.argv[2])
        temp = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x09
        set_cct(ser, bri, temp)

    elif cmd == "on":
        set_cct(ser, 100, 0x09)

    elif cmd == "off":
        set_cct(ser, 0, 0x09)

    elif cmd == "status":
        read_status(ser)

    elif cmd == "temp-scan":
        temp_scan(ser)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    ser.close()


if __name__ == "__main__":
    main()
