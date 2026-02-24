#!/usr/bin/env python3
"""
Neewer PL81-Pro — Interactive temperature calibration.

Walks you through temperature byte values and asks you to describe the
color you see. Uses plain language — just say what you see.

The PL81-Pro range is 2900K-7000K (warm orange → cool daylight).

Usage:
    python3 temp_calibrate.py
"""

import serial
import glob
import sys
import time
import json


def find_serial_port():
    ports = glob.glob("/dev/cu.usbserial-*")
    if not ports:
        print("Error: No USB serial port found. Is the light connected?")
        sys.exit(1)
    return ports[0]


def usb_checksum(data: bytes) -> bytes:
    s = sum(data) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


def set_temp(ser, temp_byte, brightness=100):
    brightness = max(0, min(100, brightness))
    payload = bytes([0x3A, 0x02, 0x03, 0x01, brightness, temp_byte])
    cmd = payload + usb_checksum(payload)
    ser.reset_input_buffer()
    ser.write(cmd)
    ser.flush()
    time.sleep(0.3)
    ser.read(ser.in_waiting or 0)  # drain echo


def main():
    port = find_serial_port()
    ser = serial.Serial(port, 115200, timeout=1)
    time.sleep(0.2)
    ser.read(ser.in_waiting or 0)

    print("=" * 60)
    print("  Neewer PL81-Pro — Temperature Calibration")
    print("=" * 60)
    print()
    print("I'll step through temperature values on your light.")
    print("For each one, tell me what you see. Keep it simple:")
    print()
    print("  warmest / very warm / warm / neutral / cool / coolest")
    print("  or: same as last / no change / skip")
    print()
    print("You can also say things like:")
    print("  'orange' 'yellowish' 'white' 'blueish'")
    print()
    print("Type 'q' to quit, 'r' to repeat, 'b' to go back one.")
    print("Type a number (0-63) to jump to that value.")
    print()
    input("Press Enter when you're ready...")
    print()

    # We know 0x00-0x3F are accepted. Test them all.
    results = {}
    i = 0
    values = list(range(0x00, 0x40))  # 0-63

    while i < len(values):
        t = values[i]
        set_temp(ser, t)

        prompt = f"  [{i+1}/{len(values)}] temp=0x{t:02x} ({t}) → What do you see? "
        answer = input(prompt).strip()

        if not answer:
            i += 1
            continue
        elif answer.lower() == 'q':
            break
        elif answer.lower() == 'r':
            continue  # repeat same value
        elif answer.lower() == 'b':
            i = max(0, i - 1)
            continue
        elif answer.isdigit():
            jump = int(answer)
            if 0 <= jump <= 63:
                i = jump
                continue
            else:
                print("    (value must be 0-63)")
                continue
        elif answer.lower() in ('skip', 's'):
            i += 1
            continue
        else:
            results[t] = answer
            i += 1

    print()
    print("=" * 60)
    print("  Results")
    print("=" * 60)
    print()

    if results:
        for t in sorted(results.keys()):
            print(f"  0x{t:02x} ({t:2d}): {results[t]}")

        # Save to file
        out = {f"0x{t:02x}": {"decimal": t, "description": results[t]}
               for t in sorted(results.keys())}
        with open("temp_calibration.json", "w") as f:
            json.dump(out, f, indent=2)
        print()
        print(f"  Saved to temp_calibration.json")
    else:
        print("  No data recorded.")

    ser.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
