#!/usr/bin/env python3
"""
Probe the Neewer PL81-Pro via USB HID with correct 192-byte report size.

HID report descriptor analysis:
  - Usage page: 0xFFDA (vendor-specific)
  - Output: 192 bytes, report ID 0, usage 0xD1
  - Input:  192 bytes, report ID 0, usage 0xD2
  - No feature reports

Commands must be sent as exactly 192-byte output reports, zero-padded.
"""

import glob
import sys
import threading
import time

import hid
import serial


REALTEK_VID = 0x0BDA
REALTEK_PID = 0x1100
REPORT_SIZE = 192


def checksum_ble(data: bytes) -> int:
    return sum(data) & 0xFF


def build_cmd(prefix: int, tag: int, payload: bytes) -> bytes:
    frame = bytes([prefix, tag, len(payload)]) + payload
    return frame + bytes([checksum_ble(frame)])


def pad_report(cmd: bytes, report_id: int = 0x00) -> bytes:
    """Pad command to a full 192-byte HID output report with report ID."""
    # hidapi on macOS: first byte is report ID, followed by report data
    return bytes([report_id]) + cmd.ljust(REPORT_SIZE, b'\x00')


def find_serial_port() -> str:
    candidates = glob.glob("/dev/cu.usbserial-*")
    return candidates[0] if candidates else None


def serial_listener(port: str, stop_event: threading.Event):
    try:
        ser = serial.Serial(port=port, baudrate=115200, timeout=0.5)
    except serial.SerialException as e:
        print(f"  [serial] Could not open {port}: {e}")
        return
    print(f"  [serial] Listening on {port}")
    while not stop_event.is_set():
        data = ser.read(64)
        if data:
            print(f"  [serial] << STATUS ({len(data)} bytes): [{data.hex(' ')}]")
    ser.close()


def try_send(dev, cmd: bytes, label: str, wait: float = 1.5):
    """Send a 192-byte padded HID report and check for response."""
    report = pad_report(cmd)
    short_hex = cmd.hex(" ")
    print(f"  >> {label:<45s}  [{short_hex}]")
    try:
        n = dev.write(report)
        if n < 0:
            print(f"     write failed: {n}")
            return
    except Exception as e:
        print(f"     write error: {e}")
        return

    # Check for HID input report response
    start = time.time()
    while time.time() - start < wait:
        try:
            resp = dev.read(REPORT_SIZE, timeout_ms=100)
            if resp:
                # Trim trailing zeros for display
                trimmed = bytes(resp).rstrip(b'\x00')
                print(f"  << HID RESPONSE ({len(trimmed)} non-zero bytes): [{trimmed.hex(' ')}]")
        except Exception:
            break

    time.sleep(0.3)


def main():
    print("Neewer PL81-Pro HID Probe (192-byte reports)")
    print(f"VID={hex(REALTEK_VID)} PID={hex(REALTEK_PID)} Report size={REPORT_SIZE}")
    print()

    # Start serial listener
    serial_port = find_serial_port()
    stop_serial = threading.Event()
    if serial_port:
        t = threading.Thread(target=serial_listener, args=(serial_port, stop_serial), daemon=True)
        t.start()
    else:
        print("  [serial] No serial port found")

    # Find and open the HID device with 192-byte reports
    devices = hid.enumerate(REALTEK_VID, REALTEK_PID)
    if not devices:
        print("ERROR: HID device not found")
        sys.exit(1)

    print(f"Found {len(devices)} HID interface(s)")

    for idx, dev_info in enumerate(devices):
        print(f"\n{'='*60}")
        print(f"  Interface {idx}: {dev_info['path']}")
        print(f"{'='*60}\n")

        try:
            dev = hid.device()
            dev.open_path(dev_info['path'])
            dev.set_nonblocking(1)
        except Exception as e:
            print(f"  Failed to open: {e}")
            continue

        # --- Read unsolicited data ---
        print("  Checking for unsolicited HID data (2s)...")
        start = time.time()
        while time.time() - start < 2:
            try:
                resp = dev.read(REPORT_SIZE, timeout_ms=100)
                if resp:
                    trimmed = bytes(resp).rstrip(b'\x00')
                    print(f"  << UNSOLICITED ({len(trimmed)} bytes): [{trimmed.hex(' ')}]")
            except Exception:
                break
        print()

        # --- Round 1: BLE commands (0x78 prefix) padded to 192 bytes ---
        print("  ROUND 1: BLE commands (0x78) in 192-byte reports")
        print("  " + "-"*50)

        try_send(dev, build_cmd(0x78, 0x81, bytes([0x01])),               "Power ON")
        try_send(dev, build_cmd(0x78, 0x81, bytes([0x02])),               "Power OFF")
        try_send(dev, build_cmd(0x78, 0x87, bytes([0x64, 0x2C])),         "CCT 100% 5000K")
        try_send(dev, build_cmd(0x78, 0x87, bytes([0x0A, 0x2C])),         "CCT 10% 5000K")
        try_send(dev, build_cmd(0x78, 0x86, bytes([0x00, 0x00, 0x64, 0x64])), "RGB Red")

        input("\n  React? Enter to continue...\n")

        # --- Round 2: 0x3A prefix ---
        print("  ROUND 2: USB status prefix (0x3A)")
        print("  " + "-"*50)

        try_send(dev, build_cmd(0x3A, 0x81, bytes([0x01])),               "Power ON")
        try_send(dev, build_cmd(0x3A, 0x87, bytes([0x64, 0x2C])),         "CCT 100%")
        try_send(dev, build_cmd(0x3A, 0x87, bytes([0x0A, 0x2C])),         "CCT 10%")
        try_send(dev, build_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09, 0x00])), "Set bri=100 (tag 01)")
        try_send(dev, build_cmd(0x3A, 0x02, bytes([0x01, 0x64, 0x09, 0x00])), "Set bri=100 (tag 02)")

        input("\n  React? Enter to continue...\n")

        # --- Round 3: Alternate prefixes ---
        # The app has checkSumUsbWithData: which is separate from BLE.
        # Maybe USB uses a completely different prefix byte?
        print("  ROUND 3: Trying other prefix bytes")
        print("  " + "-"*50)

        for prefix in [0x55, 0xAA, 0x80, 0x7E, 0xA5, 0x5A, 0xFE, 0xFF, 0x00, 0x01]:
            try_send(dev, build_cmd(prefix, 0x87, bytes([0x64, 0x2C])),
                     f"CCT 100% (prefix {hex(prefix)})", wait=0.5)
            try_send(dev, build_cmd(prefix, 0x87, bytes([0x0A, 0x2C])),
                     f"CCT 10%  (prefix {hex(prefix)})", wait=0.5)

        input("\n  React? Enter to continue...\n")

        # --- Round 4: Raw byte patterns ---
        # Try some common vendor-protocol patterns
        print("  ROUND 4: Common vendor protocol patterns")
        print("  " + "-"*50)

        patterns = [
            # STX-based framing
            ("STX power on",   bytes([0x02, 0x81, 0x01, 0x01, 0x03])),
            ("STX CCT 100",    bytes([0x02, 0x87, 0x02, 0x64, 0x2C, 0x03])),
            # Neewer with dataID prefix (from checkSumUsbWithData:dataID:)
            ("dataID=1 CCT 100", bytes([0x01, 0x78, 0x87, 0x02, 0x64, 0x2C, 0x91])),
            ("dataID=2 CCT 100", bytes([0x02, 0x78, 0x87, 0x02, 0x64, 0x2C, 0x91])),
            ("dataID=0 CCT 100", bytes([0x00, 0x78, 0x87, 0x02, 0x64, 0x2C, 0x91])),
            # What if the first byte is a length?
            ("len+BLE CCT 100", bytes([0x06, 0x78, 0x87, 0x02, 0x64, 0x2C, 0x91])),
            ("len+BLE CCT 10",  bytes([0x06, 0x78, 0x87, 0x02, 0x0A, 0x2C, 0x37])),
            # All with the 0x3A status format
            ("len+3A CCT 100",  bytes([0x06, 0x3A, 0x87, 0x02, 0x64, 0x2C, 0x53])),
        ]

        for label, cmd in patterns:
            try_send(dev, cmd, label, wait=0.5)

        input("\n  React? Enter to continue...\n")

        # --- Round 5: Try reading first, then writing ---
        # Maybe the device needs to be "activated" by reading first
        print("  ROUND 5: Request device info / activation")
        print("  " + "-"*50)

        # Try sending a "get info" type command
        info_cmds = [
            ("Get info (78 85)",   build_cmd(0x78, 0x85, bytes([0x00]))),
            ("Get info (78 80)",   build_cmd(0x78, 0x80, bytes([0x00]))),
            ("Get info (3A 85)",   build_cmd(0x3A, 0x85, bytes([0x00]))),
            ("Get info (3A 00)",   build_cmd(0x3A, 0x00, bytes([0x00]))),
            # Maybe just all zeros requests info
            ("All zeros",          bytes(REPORT_SIZE)),
            # Or 0xFF
            ("All 0xFF",           bytes([0xFF] * 16)),
        ]

        for label, cmd in info_cmds:
            try_send(dev, cmd, label, wait=1.0)

        dev.close()

    stop_serial.set()
    print("\nDone.")


if __name__ == "__main__":
    main()
