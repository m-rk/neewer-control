#!/usr/bin/env python3
"""
Neewer PL81-Pro USB HID Probe v4 — Correct protocol from binary disassembly.

PROTOCOL DECODED FROM NEEWER CONTROL CENTER APP BINARY (x86_64 disassembly):

  Command format: [0x3A] [tag] [payload_len] [payload...] [cs_hi] [cs_lo]
  Checksum: 16-bit big-endian sum of all preceding bytes
  HID sending: prepend 1-byte data length, set reportID = original data length

  Commands:
    Power on:   3A 06 01 01  + 16-bit checksum
    Power off:  3A 06 01 02  + 16-bit checksum
    CCT:        3A 02 03 01 [bri] [temp] + 16-bit checksum
    HSI:        3A 04 04 [hue_lo] [hue_hi] [sat] [bri] + 16-bit checksum

RUN FROM GHOSTTY (not through Claude):
    python3 probe_usb_v4.py
"""

import ctypes
import ctypes.util
import sys
import time
import struct


def setup_iokit():
    iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("IOKit"))
    cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))

    iokit.IOHIDManagerCreate.restype = ctypes.c_void_p
    iokit.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    iokit.IOHIDManagerSetDeviceMatching.restype = None
    iokit.IOHIDManagerSetDeviceMatching.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    iokit.IOHIDManagerOpen.restype = ctypes.c_uint32
    iokit.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    iokit.IOHIDManagerCopyDevices.restype = ctypes.c_void_p
    iokit.IOHIDManagerCopyDevices.argtypes = [ctypes.c_void_p]
    iokit.IOHIDDeviceGetProperty.restype = ctypes.c_void_p
    iokit.IOHIDDeviceGetProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    iokit.IOHIDDeviceOpen.restype = ctypes.c_uint32
    iokit.IOHIDDeviceOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    iokit.IOHIDDeviceClose.restype = ctypes.c_uint32
    iokit.IOHIDDeviceClose.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    iokit.IOHIDDeviceSetReport.restype = ctypes.c_uint32
    iokit.IOHIDDeviceSetReport.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_long, ctypes.c_char_p, ctypes.c_long
    ]

    cf.CFSetGetCount.restype = ctypes.c_long
    cf.CFSetGetCount.argtypes = [ctypes.c_void_p]
    cf.CFSetGetValues.restype = None
    cf.CFSetGetValues.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int32)]

    return iokit, cf


def cf_str(cf, s):
    return cf.CFStringCreateWithCString(None, s.encode(), 0x08000100)


def get_int(iokit, cf, dev, key):
    prop = iokit.IOHIDDeviceGetProperty(dev, cf_str(cf, key))
    if not prop:
        return None
    v = ctypes.c_int32()
    cf.CFNumberGetValue(prop, 3, ctypes.byref(v))
    return v.value


def usb_checksum(data: bytes) -> bytes:
    """16-bit big-endian sum of all bytes (from checkSumWithUsbData: disassembly)."""
    s = sum(data) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


def build_cmd(payload: bytes) -> bytes:
    """Build complete USB command: payload + 16-bit big-endian checksum."""
    return payload + usb_checksum(payload)


def send_report(iokit, device, data, report_id, label, pad_to=0):
    """Send HID output report."""
    if pad_to > 0:
        report = data.ljust(pad_to, b"\x00")
    else:
        report = data
    ret = iokit.IOHIDDeviceSetReport(device, 1, report_id, report, len(report))
    status = "OK!" if ret == 0 else f"0x{ret:08x}"
    hex_str = data[:20].hex(" ")
    if len(data) > 20:
        hex_str += " ..."
    print(f"  {label:<50s} id={report_id:<4d} len={len(report):<4d} [{hex_str}] -> {status}")
    return ret == 0


def main():
    print("=" * 70)
    print("  Neewer PL81-Pro USB HID Probe v4")
    print("  Protocol decoded from binary disassembly")
    print("  Run directly from Ghostty, NOT through Claude!")
    print("=" * 70)
    print()

    iokit, cf = setup_iokit()

    mgr = iokit.IOHIDManagerCreate(None, 0)
    iokit.IOHIDManagerSetDeviceMatching(mgr, None)
    ret = iokit.IOHIDManagerOpen(mgr, 0)
    if ret != 0:
        print(f"Failed to open HID manager: 0x{ret:08x}")
        sys.exit(1)

    ds = iokit.IOHIDManagerCopyDevices(mgr)
    count = cf.CFSetGetCount(ds)
    devs = (ctypes.c_void_p * count)()
    cf.CFSetGetValues(ds, devs)

    target = None
    for i in range(count):
        d = devs[i]
        vid = get_int(iokit, cf, d, "VendorID")
        pid = get_int(iokit, cf, d, "ProductID")
        if vid == 0x0BDA and pid == 0x1100:
            target = d
            print(f"Found: Realtek HID VID=0x{vid:04x} PID=0x{pid:04x}")
            ret = iokit.IOHIDDeviceOpen(d, 0)
            print(f"  Open: 0x{ret:08x}")
            if ret != 0:
                print("  Failed!")
                continue
            break

    if target is None:
        print("Realtek HID device (0x0BDA:0x1100) not found!")
        sys.exit(1)

    print()
    any_ok = False

    # === Build commands ===
    # From disassembly:
    #   publishUsbTurnOn:         3A 06 01 [01/02]
    #   publishUsbCCT:            3A 02 03 01 [bri] [temp]
    #   publishUsbHSI:            via checkSumUsbWithData:dataID:4
    #                             → 3A 04 04 [hue_lo] [hue_hi] [sat] [bri]

    power_on  = build_cmd(bytes([0x3A, 0x06, 0x01, 0x01]))
    power_off = build_cmd(bytes([0x3A, 0x06, 0x01, 0x02]))
    cct_100   = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x64, 0x09]))
    cct_10    = build_cmd(bytes([0x3A, 0x02, 0x03, 0x01, 0x0A, 0x09]))
    hsi_red   = build_cmd(bytes([0x3A, 0x04, 0x04, 0x00, 0x00, 0x64, 0x64]))

    # === ROUND 1: Exact app protocol (length prefix + reportID = data length) ===
    print("--- Round 1: Exact app protocol (length prefix, reportID=dataLen) ---")
    for label, cmd in [
        ("Power ON",  power_on),
        ("CCT 100% 7000K", cct_100),
        ("CCT 10% 7000K",  cct_10),
        ("Power OFF", power_off),
    ]:
        # App prepends 1-byte length then sends with reportID = original data length
        data_with_prefix = bytes([len(cmd)]) + cmd
        report_id = len(cmd)
        ok = send_report(iokit, target, data_with_prefix, report_id, label, pad_to=192)
        if ok:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 2: Same format, reportID=0 ===
    print("--- Round 2: Length prefix, reportID=0 ---")
    for label, cmd in [
        ("Power ON",  power_on),
        ("CCT 100% 7000K", cct_100),
    ]:
        data_with_prefix = bytes([len(cmd)]) + cmd
        ok = send_report(iokit, target, data_with_prefix, 0, label, pad_to=192)
        if ok:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 3: No length prefix, reportID=0, padded to 192 ===
    print("--- Round 3: No length prefix, reportID=0, padded to 192 ---")
    for label, cmd in [
        ("Power ON",  power_on),
        ("CCT 100% 7000K", cct_100),
    ]:
        ok = send_report(iokit, target, cmd, 0, label, pad_to=192)
        if ok:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 4: No padding (exact length) ===
    print("--- Round 4: Exact length, no padding ---")
    for label, cmd, rid in [
        ("Power ON (rid=dataLen)", power_on, len(power_on)),
        ("Power ON (rid=0)",       power_on, 0),
        ("CCT 100% (rid=dataLen)", cct_100,  len(cct_100)),
        ("CCT 100% (rid=0)",      cct_100,  0),
    ]:
        ok = send_report(iokit, target, cmd, rid, label)
        if ok:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 5: With length prefix, exact length (no padding) ===
    print("--- Round 5: Length prefix, exact length, no padding ---")
    for label, cmd, rid in [
        ("Power ON", power_on, len(power_on)),
        ("CCT 100%", cct_100, len(cct_100)),
    ]:
        data_with_prefix = bytes([len(cmd)]) + cmd
        ok = send_report(iokit, target, data_with_prefix, rid, label)
        if ok:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 6: Try kIOHIDReportTypeInput (0) instead of Output (1) ===
    print("--- Round 6: Report type = Input (0) instead of Output (1) ---")
    for label, cmd in [("Power ON", power_on), ("CCT 100%", cct_100)]:
        data_with_prefix = bytes([len(cmd)]) + cmd
        report = data_with_prefix.ljust(192, b"\x00")
        # Use type=0 (Input) instead of type=1 (Output)
        ret = iokit.IOHIDDeviceSetReport(target, 0, len(cmd), report, len(report))
        status = "OK!" if ret == 0 else f"0x{ret:08x}"
        hex_str = data_with_prefix[:16].hex(" ")
        print(f"  {label:<50s} type=Input [{hex_str}] -> {status}")
        if ret == 0:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 7: Try kIOHIDReportTypeFeature (2) ===
    print("--- Round 7: Report type = Feature (2) ---")
    for label, cmd in [("Power ON", power_on), ("CCT 100%", cct_100)]:
        data_with_prefix = bytes([len(cmd)]) + cmd
        report = data_with_prefix.ljust(192, b"\x00")
        ret = iokit.IOHIDDeviceSetReport(target, 2, len(cmd), report, len(report))
        status = "OK!" if ret == 0 else f"0x{ret:08x}"
        hex_str = data_with_prefix[:16].hex(" ")
        print(f"  {label:<50s} type=Feature [{hex_str}] -> {status}")
        if ret == 0:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 8: 1-byte checksum variant (serial-style) ===
    print("--- Round 8: 1-byte checksum (like serial status) for comparison ---")
    for label, payload in [
        ("Power ON (1-byte cs)", bytes([0x3A, 0x06, 0x01, 0x01])),
        ("CCT 100% (1-byte cs)", bytes([0x3A, 0x02, 0x03, 0x01, 0x64, 0x09])),
    ]:
        cs1 = sum(payload) & 0xFF
        cmd_1byte = payload + bytes([cs1])
        data = bytes([len(cmd_1byte)]) + cmd_1byte
        ok = send_report(iokit, target, data, len(cmd_1byte), label, pad_to=192)
        if ok:
            any_ok = True
            time.sleep(1)

    print()

    # === ROUND 9: BLE format commands (0x78 prefix) with 16-bit USB checksum ===
    print("--- Round 9: BLE commands with 16-bit USB checksum ---")
    ble_power_on = bytes([0x78, 0x81, 0x01, 0x01])
    ble_cct = bytes([0x78, 0x87, 0x02, 0x64, 0x2C])
    for label, payload in [
        ("BLE Power ON + USB cs", ble_power_on),
        ("BLE CCT 100% + USB cs", ble_cct),
    ]:
        cmd = payload + usb_checksum(payload)
        data = bytes([len(cmd)]) + cmd
        ok = send_report(iokit, target, data, len(cmd), label, pad_to=192)
        if ok:
            any_ok = True
            time.sleep(1)

    print()

    if any_ok:
        print("*** SUCCESS! At least one command worked! ***")
    else:
        print("All commands failed. The 0xe0005000 error is likely:")
        print("  - USB pipe stall (device rejects the report)")
        print("  - macOS entitlement issue (needs com.apple.security.device.usb)")
        print("  - Missing initialization handshake")
        print()
        print("Try: hidapitester or cython-hidapi for alternative HID access")

    iokit.IOHIDDeviceClose(target, 0)
    print("\nDone.")


if __name__ == "__main__":
    main()
