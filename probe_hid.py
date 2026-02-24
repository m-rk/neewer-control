#!/usr/bin/env python3
"""
Probe the Neewer PL81-Pro via USB HID (Realtek VID 0x0BDA, PID 0x1100).

Discovery from reverse engineering the NEEWER Control Center binary:
  - Commands are sent via HID reports (setReport:data:length:reportID:)
  - Status comes back over the CH340 serial port
  - Separate USB checksum (checkSumUsbWithData:dataID:)

This script tries various command formats over HID while monitoring
the serial port for status responses.
"""

import glob
import sys
import threading
import time

import hid
import serial


REALTEK_VID = 0x0BDA
REALTEK_PID = 0x1100


def checksum_ble(data: bytes) -> int:
    """BLE-style checksum: sum(bytes) & 0xFF"""
    return sum(data) & 0xFF


def build_ble_cmd(prefix: int, tag: int, payload: bytes) -> bytes:
    """BLE-style: <prefix> <tag> <len> <payload> <checksum>"""
    frame = bytes([prefix, tag, len(payload)]) + payload
    return frame + bytes([checksum_ble(frame)])


def find_serial_port() -> str:
    candidates = glob.glob("/dev/cu.usbserial-*")
    if not candidates:
        return None
    return candidates[0]


def serial_listener(port: str, stop_event: threading.Event):
    """Background thread that reads serial port status packets."""
    try:
        ser = serial.Serial(port=port, baudrate=115200, timeout=0.5)
    except serial.SerialException as e:
        print(f"  [serial] Could not open {port}: {e}")
        return

    print(f"  [serial] Listening on {port}")
    while not stop_event.is_set():
        data = ser.read(64)
        if data:
            print(f"  [serial] << LIGHT STATUS ({len(data)} bytes): [{data.hex(' ')}]")
    ser.close()


def send_hid(dev, data: bytes, label: str):
    """Send bytes to the HID device and log."""
    hex_str = data.hex(" ")
    print(f"  >> HID {label:<40s}  [{hex_str}]")
    try:
        # Try as feature report (report type 3 in IOKit)
        result = dev.send_feature_report(data)
        if result >= 0:
            print(f"     send_feature_report: OK ({result})")
    except Exception as e:
        print(f"     send_feature_report: {e}")

    try:
        # Try as output report (report type 2 in IOKit)
        result = dev.write(data)
        if result >= 0:
            print(f"     write: OK ({result})")
    except Exception as e:
        print(f"     write: {e}")

    # Try to read back
    try:
        response = dev.read(64, timeout_ms=300)
        if response:
            print(f"  << HID RESPONSE ({len(response)} bytes): [{bytes(response).hex(' ')}]")
    except Exception:
        pass

    time.sleep(1.0)


def main():
    print("Neewer PL81-Pro HID Probe")
    print(f"Looking for Realtek HID: VID={hex(REALTEK_VID)} PID={hex(REALTEK_PID)}")
    print()

    # Start serial listener in background
    serial_port = find_serial_port()
    stop_serial = threading.Event()
    if serial_port:
        serial_thread = threading.Thread(
            target=serial_listener, args=(serial_port, stop_serial), daemon=True
        )
        serial_thread.start()
    else:
        print("  [serial] No serial port found, skipping serial monitoring")

    # Open HID device
    devices = hid.enumerate(REALTEK_VID, REALTEK_PID)
    if not devices:
        print("ERROR: Realtek HID device not found. Is the light plugged in?")
        sys.exit(1)

    print(f"Found {len(devices)} HID interface(s)")
    for i, d in enumerate(devices):
        print(f"  [{i}] path={d['path']} usage_page={hex(d['usage_page'])} usage={hex(d['usage'])}")
    print()

    # Try each HID interface
    for idx, dev_info in enumerate(devices):
        print(f"{'='*60}")
        print(f"  HID Interface {idx}: {dev_info['path']}")
        print(f"{'='*60}")

        try:
            dev = hid.device()
            dev.open_path(dev_info['path'])
            dev.set_nonblocking(1)
        except Exception as e:
            print(f"  Failed to open: {e}")
            continue

        # Get device info
        try:
            mfr = dev.get_manufacturer_string()
            prod = dev.get_product_string()
            print(f"  Manufacturer: {mfr}")
            print(f"  Product: {prod}")
        except Exception:
            pass
        print()

        # --- Try reading any unsolicited HID data ---
        print("  Reading any unsolicited HID data (2 sec)...")
        start = time.time()
        while time.time() - start < 2:
            try:
                data = dev.read(64, timeout_ms=100)
                if data:
                    print(f"  << HID UNSOLICITED: [{bytes(data).hex(' ')}]")
            except Exception:
                break
        print()

        # --- Round 1: BLE commands with 0x78 prefix ---
        print("  ROUND 1: BLE format (0x78 prefix)")
        print("  " + "-" * 50)

        cmds_78 = [
            ("Power ON",    build_ble_cmd(0x78, 0x81, bytes([0x01]))),
            ("Power OFF",   build_ble_cmd(0x78, 0x81, bytes([0x02]))),
            ("CCT 100%",    build_ble_cmd(0x78, 0x87, bytes([0x64, 0x2C]))),
            ("CCT 10%",     build_ble_cmd(0x78, 0x87, bytes([0x0A, 0x2C]))),
            ("RGB Red",     build_ble_cmd(0x78, 0x86, bytes([0x00, 0x00, 0x64, 0x64]))),
        ]

        for label, cmd in cmds_78:
            # HID reports often need a report ID prepended (0x00 for default)
            send_hid(dev, bytes([0x00]) + cmd, label + " (0x00 prefix)")
            send_hid(dev, cmd, label + " (raw)")

        input("\n  Did the light react? Press Enter to continue...\n")

        # --- Round 2: 0x3A prefix (matches serial status format) ---
        print("  ROUND 2: USB format (0x3A prefix)")
        print("  " + "-" * 50)

        cmds_3a = [
            ("Power ON",  build_ble_cmd(0x3A, 0x81, bytes([0x01]))),
            ("Power OFF", build_ble_cmd(0x3A, 0x81, bytes([0x02]))),
            ("CCT 100%",  build_ble_cmd(0x3A, 0x87, bytes([0x64, 0x2C]))),
            ("CCT 10%",   build_ble_cmd(0x3A, 0x87, bytes([0x0A, 0x2C]))),
            # Echo the status format as a command
            ("Set 100%",  build_ble_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09, 0x00]))),
            ("Set 10%",   build_ble_cmd(0x3A, 0x01, bytes([0x01, 0x0A, 0x09, 0x00]))),
        ]

        for label, cmd in cmds_3a:
            send_hid(dev, bytes([0x00]) + cmd, label + " (0x00 prefix)")
            send_hid(dev, cmd, label + " (raw)")

        input("\n  Did the light react? Press Enter to continue...\n")

        # --- Round 3: Padded to fixed report sizes ---
        # HID reports are often fixed-size (8, 16, 32, or 64 bytes)
        print("  ROUND 3: Fixed-size HID reports (padded)")
        print("  " + "-" * 50)

        base_cmd = build_ble_cmd(0x78, 0x87, bytes([0x64, 0x2C]))  # CCT 100%
        for report_size in [8, 16, 32, 64]:
            padded = base_cmd.ljust(report_size, b'\x00')
            send_hid(dev, bytes([0x00]) + padded, f"CCT 100% padded to {report_size}B (+reportID)")
            send_hid(dev, padded, f"CCT 100% padded to {report_size}B (raw)")

        base_cmd2 = build_ble_cmd(0x78, 0x87, bytes([0x0A, 0x2C]))  # CCT 10%
        for report_size in [8, 16, 32, 64]:
            padded = base_cmd2.ljust(report_size, b'\x00')
            send_hid(dev, bytes([0x00]) + padded, f"CCT 10% padded to {report_size}B (+reportID)")

        input("\n  Did the light react? Press Enter to continue...\n")

        # --- Round 4: Try get_feature_report to read device state ---
        print("  ROUND 4: Reading feature reports")
        print("  " + "-" * 50)
        for report_id in range(0, 16):
            try:
                data = dev.get_feature_report(report_id, 64)
                if data:
                    print(f"  << Feature report {report_id}: [{bytes(data).hex(' ')}]")
            except Exception as e:
                if "error" not in str(e).lower() and "unsupported" not in str(e).lower():
                    print(f"  << Feature report {report_id}: {e}")

        dev.close()
        print()

    stop_serial.set()
    print("Done.")


if __name__ == "__main__":
    main()
