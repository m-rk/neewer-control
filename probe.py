#!/usr/bin/env python3
"""
Probe the Neewer PL81-Pro over USB serial by sending known BLE protocol
commands at various baud rates. Watch the light for physical changes.
"""

import sys
import time
import glob
import serial


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_cmd(tag: int, payload: bytes) -> bytes:
    """Build a Neewer command: 0x78 <tag> <len> <payload...> <checksum>"""
    frame = bytes([0x78, tag, len(payload)]) + payload
    return frame + bytes([checksum(frame)])


# Known BLE commands
COMMANDS = {
    "power_on":       build_cmd(0x81, bytes([0x01])),
    "power_off":      build_cmd(0x81, bytes([0x02])),
    "brightness_100": build_cmd(0x87, bytes([0x64, 0x2C])),  # 100%, ~5000K
    "brightness_10":  build_cmd(0x87, bytes([0x0A, 0x2C])),  # 10%, ~5000K
    "brightness_50":  build_cmd(0x87, bytes([0x32, 0x2C])),  # 50%, ~5000K
    "cct_3200":       build_cmd(0x87, bytes([0x32, 0x20])),  # 50%, 3200K
    "cct_5600":       build_cmd(0x87, bytes([0x32, 0x38])),  # 50%, 5600K
    "rgb_red":        build_cmd(0x86, bytes([0x00, 0x00, 0x64, 0x64])),  # hue=0, sat=100, bri=100
    "rgb_green":      build_cmd(0x86, bytes([0x78, 0x00, 0x64, 0x64])),  # hue=120
    "rgb_blue":       build_cmd(0x86, bytes([0xF0, 0x00, 0x64, 0x64])),  # hue=240
}

# Baud rates to try (most common for CH340 devices)
BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 256000, 460800, 921600]

# Sequence of commands to cycle through at each baud rate.
# These should produce visible changes if the light understands them.
PROBE_SEQUENCE = [
    ("power_on",       "Power ON",           2.0),
    ("brightness_100", "Brightness -> 100%", 1.5),
    ("brightness_10",  "Brightness -> 10%",  1.5),
    ("brightness_50",  "Brightness -> 50%",  1.0),
    ("cct_3200",       "CCT -> 3200K (warm)", 1.5),
    ("cct_5600",       "CCT -> 5600K (cool)", 1.5),
    ("rgb_red",        "RGB -> Red",         1.5),
    ("rgb_green",      "RGB -> Green",       1.5),
    ("rgb_blue",       "RGB -> Blue",        1.5),
    ("power_off",      "Power OFF",          2.0),
]


def find_serial_port() -> str:
    """Auto-detect the Neewer light's serial port."""
    candidates = glob.glob("/dev/cu.usbserial-*")
    if not candidates:
        print("ERROR: No /dev/cu.usbserial-* device found. Is the light plugged in?")
        sys.exit(1)
    if len(candidates) > 1:
        print(f"Multiple serial devices found: {candidates}")
        print(f"Using first: {candidates[0]}")
    return candidates[0]


def try_read(ser: serial.Serial, timeout: float = 0.5) -> bytes:
    """Try to read any available response bytes."""
    ser.timeout = timeout
    data = ser.read(256)
    return data


def probe_baud_rate(port: str, baud: int) -> None:
    """Send the probe sequence at a specific baud rate."""
    print(f"\n{'='*60}")
    print(f"  BAUD RATE: {baud}")
    print(f"{'='*60}")
    print(f"  Watch the light for any physical changes!")
    print()

    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
            write_timeout=1,
        )
    except serial.SerialException as e:
        print(f"  Failed to open {port} at {baud}: {e}")
        return

    # Flush any stale data
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    for cmd_name, description, delay in PROBE_SEQUENCE:
        cmd_bytes = COMMANDS[cmd_name]
        hex_str = cmd_bytes.hex(" ")

        print(f"  >> {description:<25s}  [{hex_str}]")
        ser.write(cmd_bytes)
        ser.flush()

        # Check for any response
        response = try_read(ser, timeout=0.3)
        if response:
            print(f"  << RESPONSE ({len(response)} bytes): [{response.hex(' ')}]")

        time.sleep(delay)

    ser.close()


def main():
    port = find_serial_port()
    print(f"Neewer PL81-Pro Protocol Probe")
    print(f"Device: {port}")
    print()
    print("This script sends known Neewer BLE commands over USB serial")
    print("at different baud rates. Watch the light for any reaction.")
    print()
    print("Commands that will be sent at each baud rate:")
    for cmd_name, description, _ in PROBE_SEQUENCE:
        print(f"  - {description}")
    print()

    if len(sys.argv) > 1:
        # Allow testing a single baud rate: python probe.py 115200
        baud = int(sys.argv[1])
        print(f"Testing single baud rate: {baud}")
        input("Press Enter to start...")
        probe_baud_rate(port, baud)
    else:
        print(f"Will try {len(BAUD_RATES)} baud rates: {BAUD_RATES}")
        input("Press Enter to start...")
        for baud in BAUD_RATES:
            probe_baud_rate(port, baud)
            print()
            resp = input("Did the light react? [y/N/q] ").strip().lower()
            if resp == "y":
                print(f"\n*** BAUD RATE {baud} WORKS! ***")
                print("Run again with just this baud rate for detailed testing:")
                print(f"  python probe.py {baud}")
                return
            elif resp == "q":
                print("Aborted.")
                return

    print("\nDone. If no baud rate worked, the USB protocol may differ from BLE.")
    print("Next step: sniff traffic from the NEEWER Control Center app using socat.")


if __name__ == "__main__":
    main()
