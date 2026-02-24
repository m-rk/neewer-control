#!/usr/bin/env python3
"""
Direct IOKit HID probe — bypasses hidapi to get actual error codes
from IOHIDDeviceSetReport.
"""

import ctypes
import ctypes.util
import sys
import time
import glob
import threading

import serial


# Load IOKit framework
iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("IOKit"))
cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))

# Constants
kIOHIDReportTypeInput = 0
kIOHIDReportTypeOutput = 1
kIOHIDReportTypeFeature = 2
kIOHIDOptionsTypeNone = 0
kIOHIDOptionsTypeSeizeDevice = 1
kIOReturnSuccess = 0
kCFNumberSInt32Type = 3

# Type aliases
IOHIDManagerRef = ctypes.c_void_p
IOHIDDeviceRef = ctypes.c_void_p
CFSetRef = ctypes.c_void_p
CFIndex = ctypes.c_long
IOReturn = ctypes.c_uint32
CFStringRef = ctypes.c_void_p
CFNumberRef = ctypes.c_void_p
CFDictionaryRef = ctypes.c_void_p

# Function signatures
iokit.IOHIDManagerCreate.restype = IOHIDManagerRef
iokit.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

iokit.IOHIDManagerSetDeviceMatching.restype = None
iokit.IOHIDManagerSetDeviceMatching.argtypes = [IOHIDManagerRef, CFDictionaryRef]

iokit.IOHIDManagerOpen.restype = IOReturn
iokit.IOHIDManagerOpen.argtypes = [IOHIDManagerRef, ctypes.c_uint32]

iokit.IOHIDManagerCopyDevices.restype = CFSetRef
iokit.IOHIDManagerCopyDevices.argtypes = [IOHIDManagerRef]

iokit.IOHIDDeviceGetProperty.restype = ctypes.c_void_p
iokit.IOHIDDeviceGetProperty.argtypes = [IOHIDDeviceRef, CFStringRef]

iokit.IOHIDDeviceOpen.restype = IOReturn
iokit.IOHIDDeviceOpen.argtypes = [IOHIDDeviceRef, ctypes.c_uint32]

iokit.IOHIDDeviceSetReport.restype = IOReturn
iokit.IOHIDDeviceSetReport.argtypes = [
    IOHIDDeviceRef, ctypes.c_int, CFIndex,
    ctypes.c_char_p, CFIndex
]

iokit.IOHIDDeviceGetReport.restype = IOReturn
iokit.IOHIDDeviceGetReport.argtypes = [
    IOHIDDeviceRef, ctypes.c_int, CFIndex,
    ctypes.c_char_p, ctypes.POINTER(CFIndex)
]

cf.CFSetGetCount.restype = CFIndex
cf.CFSetGetCount.argtypes = [CFSetRef]

cf.CFSetGetValues.restype = None
cf.CFSetGetValues.argtypes = [CFSetRef, ctypes.POINTER(ctypes.c_void_p)]

cf.CFStringCreateWithCString.restype = CFStringRef
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]

cf.CFNumberGetValue.restype = ctypes.c_bool
cf.CFNumberGetValue.argtypes = [CFNumberRef, ctypes.c_int, ctypes.POINTER(ctypes.c_int32)]

cf.CFRelease.restype = None
cf.CFRelease.argtypes = [ctypes.c_void_p]

kCFStringEncodingUTF8 = 0x08000100


def cf_str(s):
    return cf.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)


def get_int_property(device, key):
    prop = iokit.IOHIDDeviceGetProperty(device, cf_str(key))
    if not prop:
        return None
    val = ctypes.c_int32()
    cf.CFNumberGetValue(prop, kCFNumberSInt32Type, ctypes.byref(val))
    return val.value


def ioreturn_str(ret):
    """Decode IOReturn error code."""
    errors = {
        0x00000000: "kIOReturnSuccess",
        0xe00002bc: "kIOReturnNotResponding",
        0xe00002c2: "kIOReturnUnsupported",
        0xe00002c5: "kIOReturnBadArgument",
        0xe00002c7: "kIOReturnExclusiveAccess",
        0xe00002d8: "kIOReturnAborted",
        0xe00002eb: "kIOReturnNotPermitted",
        0xe00002ed: "kIOReturnNotReady",
        0xe00002f0: "kIOReturnInternalError",
    }
    return errors.get(ret, f"0x{ret:08x}")


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_cmd(prefix: int, tag: int, payload: bytes) -> bytes:
    frame = bytes([prefix, tag, len(payload)]) + payload
    return frame + bytes([checksum(frame)])


def find_serial_port():
    candidates = glob.glob("/dev/cu.usbserial-*")
    return candidates[0] if candidates else None


def main():
    print("Neewer PL81-Pro Direct IOKit HID Probe")
    print()

    # Start serial listener
    serial_port = find_serial_port()
    if serial_port:
        print(f"Serial port: {serial_port}")

    # Create HID manager
    manager = iokit.IOHIDManagerCreate(None, kIOHIDOptionsTypeNone)
    if not manager:
        print("Failed to create HID manager")
        sys.exit(1)

    # Match Realtek VID/PID
    iokit.IOHIDManagerSetDeviceMatching(manager, None)  # match all

    ret = iokit.IOHIDManagerOpen(manager, kIOHIDOptionsTypeNone)
    print(f"HID Manager open: {ioreturn_str(ret)}")

    device_set = iokit.IOHIDManagerCopyDevices(manager)
    if not device_set:
        print("No HID devices found")
        sys.exit(1)

    count = cf.CFSetGetCount(device_set)
    print(f"Total HID devices: {count}")

    devices = (ctypes.c_void_p * count)()
    cf.CFSetGetValues(device_set, devices)

    # Find Realtek devices
    realtek_devices = []
    for i in range(count):
        dev = devices[i]
        vid = get_int_property(dev, "VendorID")
        pid = get_int_property(dev, "ProductID")
        if vid == 0x0BDA and pid == 0x1100:
            usage_page = get_int_property(dev, "PrimaryUsagePage")
            usage = get_int_property(dev, "PrimaryUsage")
            max_out = get_int_property(dev, "MaxOutputReportSize")
            max_in = get_int_property(dev, "MaxInputReportSize")
            max_feat = get_int_property(dev, "MaxFeatureReportSize")
            print(f"\n  Realtek HID: VID={hex(vid)} PID={hex(pid)}")
            print(f"  UsagePage={hex(usage_page or 0)} Usage={hex(usage or 0)}")
            print(f"  MaxOutput={max_out} MaxInput={max_in} MaxFeature={max_feat}")
            realtek_devices.append((dev, max_out or 192, max_in or 192))

    if not realtek_devices:
        print("No Realtek HID devices found")
        sys.exit(1)

    for idx, (dev, max_out, max_in) in enumerate(realtek_devices):
        print(f"\n{'='*60}")
        print(f"  Device {idx}: MaxOutput={max_out} MaxInput={max_in}")
        print(f"{'='*60}")

        # Open the device
        ret = iokit.IOHIDDeviceOpen(dev, kIOHIDOptionsTypeNone)
        print(f"  Open: {ioreturn_str(ret)}")
        if ret != kIOReturnSuccess:
            print(f"  Failed to open device!")
            continue

        # Try output report with exact max size
        print(f"\n  --- Output Reports (type={kIOHIDReportTypeOutput}) ---")

        cmds = [
            ("BLE Power ON",  build_cmd(0x78, 0x81, bytes([0x01]))),
            ("BLE CCT 100%",  build_cmd(0x78, 0x87, bytes([0x64, 0x2C]))),
            ("BLE CCT 10%",   build_cmd(0x78, 0x87, bytes([0x0A, 0x2C]))),
            ("3A Power ON",   build_cmd(0x3A, 0x81, bytes([0x01]))),
            ("3A CCT 100%",   build_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09]))),
        ]

        for label, cmd in cmds:
            # Pad to exact output report size
            padded = cmd.ljust(max_out, b'\x00')
            ret = iokit.IOHIDDeviceSetReport(
                dev, kIOHIDReportTypeOutput, 0,
                padded, len(padded)
            )
            status = ioreturn_str(ret)
            print(f"  >> {label:<30s} SetReport(Output, 0, {len(padded)}B): {status}")
            if ret == kIOReturnSuccess:
                print(f"     *** SUCCESS! ***")
            time.sleep(0.5)

        # Try feature report
        print(f"\n  --- Feature Reports (type={kIOHIDReportTypeFeature}) ---")
        for label, cmd in cmds[:2]:
            padded = cmd.ljust(max_out, b'\x00')
            ret = iokit.IOHIDDeviceSetReport(
                dev, kIOHIDReportTypeFeature, 0,
                padded, len(padded)
            )
            print(f"  >> {label:<30s} SetReport(Feature, 0, {len(padded)}B): {ioreturn_str(ret)}")
            time.sleep(0.5)

        # Try different report sizes
        print(f"\n  --- Trying different report sizes ---")
        test_cmd = build_cmd(0x78, 0x87, bytes([0x64, 0x2C]))
        for size in [5, 6, 7, 8, 16, 32, 64, 128, 191, 192, 193, 256]:
            padded = test_cmd.ljust(size, b'\x00')[:size]
            ret = iokit.IOHIDDeviceSetReport(
                dev, kIOHIDReportTypeOutput, 0,
                padded, len(padded)
            )
            status = ioreturn_str(ret)
            marker = " ***" if ret == kIOReturnSuccess else ""
            print(f"  >> Size={size:<4d} SetReport(Output): {status}{marker}")

        # Try different report IDs
        print(f"\n  --- Trying different report IDs ---")
        padded = test_cmd.ljust(max_out, b'\x00')
        for rid in [0, 1, 2, 3, 0xD1, 0xD2, 0xDA, 0xFF]:
            ret = iokit.IOHIDDeviceSetReport(
                dev, kIOHIDReportTypeOutput, rid,
                padded, len(padded)
            )
            status = ioreturn_str(ret)
            marker = " ***" if ret == kIOReturnSuccess else ""
            print(f"  >> ReportID={hex(rid):<6s} SetReport(Output): {status}{marker}")

        # Try reading input reports
        print(f"\n  --- Reading Input Reports ---")
        buf = ctypes.create_string_buffer(max_in)
        length = CFIndex(max_in)
        ret = iokit.IOHIDDeviceGetReport(
            dev, kIOHIDReportTypeInput, 0,
            buf, ctypes.byref(length)
        )
        print(f"  << GetReport(Input, 0): {ioreturn_str(ret)}, len={length.value}")
        if ret == kIOReturnSuccess and length.value > 0:
            data = buf.raw[:length.value].rstrip(b'\x00')
            print(f"     [{data.hex(' ')}]")

    print("\nDone.")


if __name__ == "__main__":
    main()
