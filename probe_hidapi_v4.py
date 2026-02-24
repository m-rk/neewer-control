#!/usr/bin/env python3
"""
Neewer PL81-Pro probe using cython-hidapi (hid module).
Uses libhidapi instead of raw IOKit — may bypass TCC differently.

Protocol from binary disassembly:
  Command:  [0x3A] [tag] [payload_len] [payload...] [cs_hi] [cs_lo]
  Sending:  prepend 1-byte length, reportID = data length
  hid.write() auto-prepends report ID byte

RUN FROM GHOSTTY:
    python3 probe_hidapi_v4.py
"""

import sys
import time

try:
    import hid
except ImportError:
    print("Install: pip3 install hidapi")
    sys.exit(1)


def usb_checksum(data: bytes) -> bytes:
    """16-bit big-endian sum of all bytes."""
    s = sum(data) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


def build_cmd(payload: bytes) -> bytes:
    """Build: payload + 16-bit big-endian checksum."""
    return payload + usb_checksum(payload)


def main():
    print("=" * 60)
    print("  Neewer PL81-Pro — cython-hidapi probe")
    print("  Protocol decoded from binary disassembly")
    print("=" * 60)
    print()

    # Enumerate
    print("Enumerating HID devices (0x0BDA:0x1100)...")
    devs = hid.enumerate(0x0BDA, 0x1100)
    if not devs:
        print("  No Realtek HID device found!")
        print("  Is the light connected via USB?")
        # Show all devices for debugging
        print("\n  All HID devices:")
        for d in hid.enumerate():
            print(f"    VID=0x{d['vendor_id']:04x} PID=0x{d['product_id']:04x} "
                  f"usage_page=0x{d['usage_page']:04x} usage=0x{d['usage']:04x} "
                  f"path={d['path']}")
        sys.exit(1)

    for d in devs:
        print(f"  Found: VID=0x{d['vendor_id']:04x} PID=0x{d['product_id']:04x} "
              f"usage_page=0x{d['usage_page']:04x} path={d['path']}")

    print()

    # Open device
    try:
        h = hid.device()
        h.open(0x0BDA, 0x1100)
        mfr = h.get_manufacturer_string() or "?"
        prod = h.get_product_string() or "?"
        print(f"Opened: {mfr} / {prod}")
    except Exception as e:
        print(f"Failed to open: {e}")
        # Try opening by path instead
        print("Trying to open by path...")
        for d in devs:
            try:
                h = hid.device()
                h.open_path(d['path'])
                print(f"  Opened via path: {d['path']}")
                break
            except Exception as e2:
                print(f"  Path {d['path']} failed: {e2}")
        else:
            print("All open attempts failed.")
            sys.exit(1)

    print()
    any_ok = False

    # === Build commands ===
    power_on  = build_cmd(bytes([0x3A, 0x06, 0x01, 0x01]))
    power_off = build_cmd(bytes([0x3A, 0x06, 0x01, 0x02]))
    cct_100   = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x64, 0x09]))
    cct_10    = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x0A, 0x09]))

    def try_write(data, label):
        nonlocal any_ok
        hex_str = data[:20].hex(" ")
        if len(data) > 20:
            hex_str += " ..."
        try:
            n = h.write(list(data))
            status = f"wrote {n} bytes"
            if n > 0:
                any_ok = True
            print(f"  {label:<50s} [{hex_str}] -> {status}")
            return n > 0
        except Exception as e:
            print(f"  {label:<50s} [{hex_str[:40]}] -> ERROR: {e}")
            return False

    # === ROUND 1: hid.write() with report ID 0x00 prepended ===
    # hid.write() expects first byte = report ID
    print("--- Round 1: Report ID 0x00 + command, padded to 193 ---")
    print("    (hid.write first byte = report ID)")
    for label, cmd in [
        ("Power ON",      power_on),
        ("CCT 100% 7000K", cct_100),
        ("CCT 10% 7000K",  cct_10),
        ("Power OFF",     power_off),
    ]:
        # Report ID 0 + command padded to 192 = 193 total
        data = bytes([0x00]) + cmd.ljust(192, b"\x00")
        ok = try_write(data, label)
        if ok:
            time.sleep(1)

    print()

    # === ROUND 2: Report ID 0x00 + length prefix + command ===
    print("--- Round 2: Report ID 0x00 + length prefix + command, padded to 193 ---")
    for label, cmd in [
        ("Power ON",      power_on),
        ("CCT 100% 7000K", cct_100),
    ]:
        data_with_prefix = bytes([len(cmd)]) + cmd
        data = bytes([0x00]) + data_with_prefix.ljust(192, b"\x00")
        ok = try_write(data, label)
        if ok:
            time.sleep(1)

    print()

    # === ROUND 3: Report ID = data length (as app does) ===
    print("--- Round 3: Report ID = data length + length prefix + command ---")
    for label, cmd in [
        ("Power ON",      power_on),
        ("CCT 100% 7000K", cct_100),
    ]:
        data_with_prefix = bytes([len(cmd)]) + cmd
        data = bytes([len(cmd)]) + data_with_prefix.ljust(192, b"\x00")
        ok = try_write(data, label)
        if ok:
            time.sleep(1)

    print()

    # === ROUND 4: Minimal data (no padding) ===
    print("--- Round 4: Minimal, no padding ---")
    for label, cmd in [
        ("Power ON rid=0",      power_on),
        ("CCT 100% rid=0",      cct_100),
    ]:
        data = bytes([0x00]) + cmd
        ok = try_write(data, label)
        if ok:
            time.sleep(1)

    print()

    # === ROUND 5: BLE commands with USB checksum ===
    print("--- Round 5: BLE format + USB 16-bit checksum ---")
    ble_pwr = build_cmd(bytes([0x78, 0x81, 0x01, 0x01]))
    ble_cct = build_cmd(bytes([0x78, 0x87, 0x02, 0x64, 0x2C]))
    for label, cmd in [
        ("BLE Power ON",  ble_pwr),
        ("BLE CCT 100%",  ble_cct),
    ]:
        data = bytes([0x00]) + cmd.ljust(192, b"\x00")
        ok = try_write(data, label)
        if ok:
            time.sleep(1)

    print()

    # === ROUND 6: Try reading first (drain any pending data) ===
    print("--- Round 6: Read first, then write ---")
    try:
        h.set_nonblocking(1)
        rd = h.read(192)
        if rd:
            print(f"  Read {len(rd)} bytes: {bytes(rd).hex(' ')}")
        else:
            print("  No pending data to read")
    except Exception as e:
        print(f"  Read error: {e}")

    data = bytes([0x00]) + power_on.ljust(192, b"\x00")
    try_write(data, "Power ON after drain")

    print()

    # === ROUND 7: Use send_feature_report ===
    print("--- Round 7: Feature report ---")
    try:
        data = bytes([0x00]) + power_on.ljust(192, b"\x00")
        n = h.send_feature_report(list(data))
        print(f"  Power ON feature report -> wrote {n} bytes")
        if n > 0:
            any_ok = True
    except AttributeError:
        # Older API: no send_feature_report, try write with feature flag
        print("  send_feature_report not available in this version")
    except Exception as e:
        print(f"  Feature report -> ERROR: {e}")

    print()

    if any_ok:
        print("*** SUCCESS! ***")
    else:
        print("All writes failed.")
        print("The 0xe0005000 error is a USB pipe stall at the device level.")
        print("This may require the com.apple.security.device.usb entitlement")
        print("signed by a proper Apple Developer ID certificate.")

    h.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
