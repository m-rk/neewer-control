#!/usr/bin/env python3
"""
Neewer PL81-Pro — focused probe after confirming power commands work.

What works: Power ON/OFF (3A 06 01 01/02 + 16-bit cs) via hid.write()
What fails: CCT (3A 02 03 01 bri temp + 16-bit cs)

This script tests CCT command variations to find the right format.

RUN FROM GHOSTTY:
    python3 probe_hidapi_v5.py
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
    return payload + usb_checksum(payload)


def try_write(h, data, label):
    hex_str = data[:24].hex(" ")
    if len(data) > 24:
        hex_str += " ..."
    try:
        n = h.write(list(data))
        err = h.error() if n == -1 else ""
        status = f"wrote {n}" + (f" ERR: {err}" if err else "")
        print(f"  {label:<55s} [{hex_str}] -> {status}")
        return n > 0
    except Exception as e:
        print(f"  {label:<55s} [{hex_str}] -> EXC: {e}")
        return False


def main():
    print("=" * 70)
    print("  Neewer PL81-Pro — CCT format probe")
    print("=" * 70)
    print()

    h = hid.device()
    h.open(0x0BDA, 0x1100)
    print(f"Opened: {h.get_manufacturer_string()} / {h.get_product_string()}")
    print()

    # === First confirm power still works ===
    print("--- Confirm: Power ON ---")
    pwr_on = build_cmd(bytes([0x3A, 0x06, 0x01, 0x01]))
    data = bytes([0x00]) + pwr_on.ljust(192, b"\x00")
    ok = try_write(h, data, "Power ON (confirmed working)")
    if ok:
        print("  >>> Does the light turn ON? Wait 2s...")
        time.sleep(2)
    print()

    # === Test CCT variations ===
    print("--- CCT command variations ---")
    print("  (Power ON worked, so device is accepting commands)")
    print()

    # Variation 1: Original decoded format
    cct = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x32, 0x09]))
    data = bytes([0x00]) + cct.ljust(192, b"\x00")
    try_write(h, data, "V1: 3A 02 03 01 [bri=50] [temp=09] + 16bit cs")

    # Variation 2: Maybe tag 0x02 needs the length prefix
    cct_raw = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x32, 0x09]))
    prefixed = bytes([len(cct_raw)]) + cct_raw
    data = bytes([0x00]) + prefixed.ljust(192, b"\x00")
    try_write(h, data, "V2: lenprefix + 3A 02 03 01 [bri] [temp] + 16bit cs")

    # Variation 3: Maybe CCT uses 1-byte checksum like serial status
    cct_1cs = bytes([0x3A, 0x02, 0x03, 0x01, 0x32, 0x09, 0x00])
    cs1 = sum(cct_1cs) & 0xFF
    cct_1cs_full = cct_1cs + bytes([cs1])
    data = bytes([0x00]) + cct_1cs_full.ljust(192, b"\x00")
    try_write(h, data, "V3: 3A 02 03 01 bri temp 00 [1-byte cs] (serial fmt)")

    # Variation 4: Maybe different tag for USB CCT
    for tag in [0x01, 0x03, 0x04, 0x05, 0x07, 0x08]:
        cct = build_cmd(bytes([0x3A, tag, 0x03, 0x01, 0x32, 0x09]))
        data = bytes([0x00]) + cct.ljust(192, b"\x00")
        try_write(h, data, f"V4: 3A {tag:02x} 03 01 bri temp + 16bit cs")

    # Variation 5: CCT with 0x00 padding byte before checksum (like serial)
    cct = bytes([0x3A, 0x02, 0x03, 0x01, 0x32, 0x09, 0x00])
    cct += usb_checksum(cct)
    data = bytes([0x00]) + cct.ljust(192, b"\x00")
    try_write(h, data, "V5: 3A 02 03 01 bri temp 00 + 16bit cs (7+2)")

    # Variation 6: Maybe payload_length byte is wrong
    for plen in [0x02, 0x04, 0x05]:
        cct = build_cmd(bytes([0x3A, 0x02, plen, 0x01, 0x32, 0x09]))
        data = bytes([0x00]) + cct.ljust(192, b"\x00")
        try_write(h, data, f"V6: 3A 02 {plen:02x} 01 bri temp + 16bit cs")

    # Variation 7: Maybe the mode byte is wrong
    for mode in [0x00, 0x02, 0x03]:
        cct = build_cmd(bytes([0x3A, 0x02, 0x03, mode, 0x32, 0x09]))
        data = bytes([0x00]) + cct.ljust(192, b"\x00")
        try_write(h, data, f"V7: 3A 02 03 {mode:02x} bri temp + 16bit cs")

    # Variation 8: Power ON with CCT in one command (publishUsbTurnOn:brightness:temperature:)
    # 3A 02 03 [on=01] [bri] [temp]
    cct = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x32, 0x09]))
    data = bytes([0x00]) + cct.ljust(192, b"\x00")
    try_write(h, data, "V8: identical to V1 (re-test after power on)")

    # Variation 9: Try the power tag (0x06) with extra brightness/temp bytes
    cct = build_cmd(bytes([0x3A, 0x06, 0x03, 0x01, 0x32, 0x09]))
    data = bytes([0x00]) + cct.ljust(192, b"\x00")
    try_write(h, data, "V9: 3A 06 03 01 bri temp (power tag + CCT data)")

    # Variation 10: No 0x3A prefix — raw BLE with 16-bit checksum
    cct = build_cmd(bytes([0x78, 0x87, 0x02, 0x32, 0x09]))
    data = bytes([0x00]) + cct.ljust(192, b"\x00")
    try_write(h, data, "V10: 78 87 02 bri temp + 16bit cs (BLE+USB cs)")

    # Variation 11: Raw BLE with 1-byte checksum
    ble_raw = bytes([0x78, 0x87, 0x02, 0x32, 0x09])
    ble_cs = sum(ble_raw) & 0xFF
    cct = ble_raw + bytes([ble_cs])
    data = bytes([0x00]) + cct.ljust(192, b"\x00")
    try_write(h, data, "V11: 78 87 02 bri temp [1-byte cs] (pure BLE)")

    # Variation 12: Just brightness (tag 0x06 with brightness)
    for bri in [0x32, 0x0A, 0x64]:
        cct = build_cmd(bytes([0x3A, 0x06, 0x02, 0x01, bri]))
        data = bytes([0x00]) + cct.ljust(192, b"\x00")
        try_write(h, data, f"V12: 3A 06 02 01 bri={bri:02x} + 16bit cs")

    print()

    # === Power OFF ===
    print("--- Power OFF ---")
    pwr_off = build_cmd(bytes([0x3A, 0x06, 0x01, 0x02]))
    data = bytes([0x00]) + pwr_off.ljust(192, b"\x00")
    try_write(h, data, "Power OFF")

    print()

    # === Try brute-force tag scan with short payloads ===
    print("--- Brute force: all tags 0x00-0x0F, payload=01 ---")
    for tag in range(0x10):
        cmd = build_cmd(bytes([0x3A, tag, 0x01, 0x01]))
        data = bytes([0x00]) + cmd.ljust(192, b"\x00")
        try_write(h, data, f"Tag 0x{tag:02x}: 3A {tag:02x} 01 01 + cs")

    print()

    h.close()
    print("Done.")


if __name__ == "__main__":
    main()
