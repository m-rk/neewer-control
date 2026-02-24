#!/usr/bin/env python3
"""
Neewer PL81-Pro — probe BOTH HID device instances.

Discovery so far:
  - Two Realtek HID devices: DevSrvsID:4296176640 and DevSrvsID:4296214651
  - Only tag 0x06 accepted (no STALL), but light doesn't respond
  - We may be writing to the wrong device instance

This probe:
  1. Enumerates both devices with full details
  2. Tries writing to each one
  3. Monitors serial port for status changes simultaneously

RUN FROM GHOSTTY:
    python3 probe_hidapi_v6.py
"""

import sys
import time
import threading

try:
    import hid
except ImportError:
    print("Install: pip3 install hidapi")
    sys.exit(1)

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


def usb_checksum(data: bytes) -> bytes:
    s = sum(data) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


def build_cmd(payload: bytes) -> bytes:
    return payload + usb_checksum(payload)


def serial_monitor(port, stop_event):
    """Monitor serial port for status packets from the light."""
    try:
        ser = serial.Serial(port, 115200, timeout=0.5)
        print(f"  [Serial] Monitoring {port}...")
        while not stop_event.is_set():
            data = ser.read(8)
            if data:
                print(f"  [Serial] Received: {data.hex(' ')}")
        ser.close()
    except Exception as e:
        print(f"  [Serial] Error: {e}")


def try_write(h, data, label):
    hex_str = data[:20].hex(" ")
    if len(data) > 20:
        hex_str += " ..."
    try:
        n = h.write(list(data))
        err = ""
        if n == -1:
            err = h.error() or "unknown"
        status = f"wrote {n}" + (f" ERR: {err}" if err else "")
        print(f"    {label:<52s} -> {status}")
        return n > 0
    except Exception as e:
        print(f"    {label:<52s} -> EXC: {e}")
        return False


def main():
    print("=" * 70)
    print("  Neewer PL81-Pro — dual device probe")
    print("=" * 70)
    print()

    # === Enumerate with full details ===
    print("--- Full HID enumeration (0x0BDA:0x1100) ---")
    devs = hid.enumerate(0x0BDA, 0x1100)
    if not devs:
        print("  No devices found!")
        sys.exit(1)

    for i, d in enumerate(devs):
        print(f"  Device {i}:")
        for key in ['vendor_id', 'product_id', 'path', 'serial_number',
                     'release_number', 'manufacturer_string', 'product_string',
                     'usage_page', 'usage', 'interface_number']:
            val = d.get(key, '?')
            if key in ('vendor_id', 'product_id', 'usage_page', 'usage'):
                print(f"    {key}: 0x{val:04x}" if isinstance(val, int) else f"    {key}: {val}")
            else:
                print(f"    {key}: {val}")
        print()

    # === Start serial monitor in background ===
    stop_serial = threading.Event()
    serial_thread = None
    if HAS_SERIAL:
        import glob
        serial_ports = glob.glob("/dev/cu.usbserial-*")
        if serial_ports:
            serial_thread = threading.Thread(target=serial_monitor,
                                            args=(serial_ports[0], stop_serial),
                                            daemon=True)
            serial_thread.start()
            time.sleep(0.5)
    else:
        print("  [Serial] pyserial not installed, skipping serial monitor")
        print()

    # === Build commands ===
    # Power commands (tag 0x06 — accepted by Realtek)
    pwr_on  = build_cmd(bytes([0x3A, 0x06, 0x01, 0x01]))
    pwr_off = build_cmd(bytes([0x3A, 0x06, 0x01, 0x02]))
    # CCT via tag 0x06 (since device only accepts 0x06)
    cct_06  = build_cmd(bytes([0x3A, 0x06, 0x03, 0x01, 0x64, 0x09]))
    cct_06b = build_cmd(bytes([0x3A, 0x06, 0x03, 0x01, 0x0A, 0x09]))
    # Original CCT format from disassembly (tag 0x02)
    cct_02  = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x64, 0x09]))

    # === Try each device ===
    for i, d in enumerate(devs):
        path = d['path']
        print(f"=== Testing Device {i}: {path} ===")
        print(f"    usage=0x{d['usage']:04x} interface={d.get('interface_number', '?')}")
        print()

        try:
            h = hid.device()
            h.open_path(path)
        except Exception as e:
            print(f"    Failed to open: {e}")
            print()
            continue

        # Test power on
        print(f"  -- Power ON --")
        data = bytes([0x00]) + pwr_on.ljust(192, b"\x00")
        ok = try_write(h, data, "3A 06 01 01 (power on)")
        time.sleep(2)
        print(f"    >>> Light changed? Check now...")
        time.sleep(1)

        # Test CCT with tag 0x06
        print(f"  -- CCT via tag 0x06 --")
        data = bytes([0x00]) + cct_06.ljust(192, b"\x00")
        try_write(h, data, "3A 06 03 01 64 09 (CCT 100% tag=06)")
        time.sleep(1)

        data = bytes([0x00]) + cct_06b.ljust(192, b"\x00")
        try_write(h, data, "3A 06 03 01 0A 09 (CCT 10% tag=06)")
        time.sleep(1)

        # Test CCT with tag 0x02
        print(f"  -- CCT via tag 0x02 (from disassembly) --")
        data = bytes([0x00]) + cct_02.ljust(192, b"\x00")
        try_write(h, data, "3A 02 03 01 64 09 (CCT 100% tag=02)")
        time.sleep(1)

        # Try reading any response
        print(f"  -- Read response --")
        h.set_nonblocking(1)
        for attempt in range(3):
            rd = h.read(192)
            if rd:
                print(f"    Read: {bytes(rd).hex(' ')}")
            else:
                if attempt == 0:
                    print(f"    No data to read")
                break
            time.sleep(0.2)

        # Power off
        print(f"  -- Power OFF --")
        data = bytes([0x00]) + pwr_off.ljust(192, b"\x00")
        try_write(h, data, "3A 06 01 02 (power off)")
        time.sleep(2)
        print(f"    >>> Light changed?")

        # Try writing raw bytes without 0x3A prefix
        print(f"  -- Raw bytes (no 0x3A prefix) --")
        for label, raw in [
            ("Just 0x01 (1 byte)",    bytes([0x01])),
            ("Just 0x06 (1 byte)",    bytes([0x06])),
            ("06 01 01 (3 bytes)",    bytes([0x06, 0x01, 0x01])),
            ("01 01 (2 bytes)",       bytes([0x01, 0x01])),
            ("FF (1 byte)",           bytes([0xFF])),
        ]:
            cmd = raw + usb_checksum(raw)
            data = bytes([0x00]) + cmd.ljust(192, b"\x00")
            try_write(h, data, f"Raw: {label}")

        print()
        h.close()

    # === Also try with the Neewer app running ===
    print("=" * 70)
    print("  If nothing worked, try running the Neewer app first,")
    print("  then close it, and immediately run this script again.")
    print("  The app may initialize the hub/light connection.")
    print("=" * 70)

    stop_serial.set()
    if serial_thread:
        serial_thread.join(timeout=2)

    print("\nDone.")


if __name__ == "__main__":
    main()
