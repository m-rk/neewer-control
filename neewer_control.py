#!/usr/bin/env python3
"""
Neewer PL81-Pro USB Control

Controls the Neewer PL81-Pro LED panel via USB serial (CH340).
Protocol reverse-engineered from the NEEWER Control Center app binary.
PL81-Pro is a bi-color (CCT-only) panel — no RGB/HSI support.

Usage:
    python3 neewer_control.py <brightness> [temperature_K]
    python3 neewer_control.py on
    python3 neewer_control.py off
    python3 neewer_control.py status

Examples:
    python3 neewer_control.py 100           # 100% brightness, default 4950K
    python3 neewer_control.py 100 2900      # 100%, warmest
    python3 neewer_control.py 100 7000      # 100%, coolest
    python3 neewer_control.py 50 4000       # 50%, warm white
    python3 neewer_control.py off           # brightness 0
    python3 neewer_control.py status        # read current state
"""

import serial
import glob
import sys
import time

# Temperature mapping: 19 steps (0x00–0x12) across 2900K–7000K.
# Values above 0x12 are clamped at 7000K by the light.
TEMP_MIN_K = 2900
TEMP_MAX_K = 7000
TEMP_STEPS = 18  # 0x00 = 2900K, 0x12 = 7000K
DEFAULT_TEMP_K = 4950  # midpoint


def kelvin_to_byte(kelvin: int) -> int:
    kelvin = max(TEMP_MIN_K, min(TEMP_MAX_K, kelvin))
    return round((kelvin - TEMP_MIN_K) * TEMP_STEPS / (TEMP_MAX_K - TEMP_MIN_K))


def byte_to_kelvin(b: int) -> int:
    b = max(0, min(TEMP_STEPS, b))
    return round(TEMP_MIN_K + b * (TEMP_MAX_K - TEMP_MIN_K) / TEMP_STEPS)


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


def set_cct(ser, brightness: int, kelvin: int = DEFAULT_TEMP_K):
    """Set CCT mode: brightness 0-100, temperature in Kelvin."""
    brightness = max(0, min(100, brightness))
    temp_byte = kelvin_to_byte(kelvin)
    actual_kelvin = byte_to_kelvin(temp_byte)
    payload = bytes([0x3A, 0x02, 0x03, 0x01, brightness, temp_byte])
    resp = send_command(ser, payload)
    status = "OK" if resp else "Sent (no echo)"
    print(f"{status}: brightness={brightness}% temp={actual_kelvin}K (0x{temp_byte:02x})")


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
                temp_byte = data[5]
                kelvin = byte_to_kelvin(temp_byte)
                print(f"  brightness={bri}% temp={kelvin}K (0x{temp_byte:02x})")
        time.sleep(0.1)


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  neewer_control.py <brightness> [temperature_K]")
        print("  neewer_control.py on")
        print("  neewer_control.py off")
        print("  neewer_control.py status")
        print()
        print(f"  Temperature: {TEMP_MIN_K}K–{TEMP_MAX_K}K (default {DEFAULT_TEMP_K}K)")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    port = find_serial_port()
    ser = serial.Serial(port, 115200, timeout=1)
    time.sleep(0.2)
    ser.read(ser.in_waiting or 0)  # drain

    if cmd == "on":
        set_cct(ser, 100)

    elif cmd == "off":
        set_cct(ser, 0)

    elif cmd == "status":
        read_status(ser)

    elif cmd.isdigit() or (cmd.startswith('-') and cmd[1:].isdigit()):
        bri = int(cmd)
        kelvin = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TEMP_K
        set_cct(ser, bri, kelvin)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    ser.close()


if __name__ == "__main__":
    main()
