# Neewer PL81-Pro USB Control — Research

## Goal

Replace the proprietary NEEWER Control Center desktop app with a custom solution
for controlling the Neewer PL81-Pro-1260740 panel light via USB-C on macOS.

---

## USB Device Identification (2026-02-24)

**Confirmed via plug/unplug test:** The PL81-Pro is the **CH340 USB Serial**
device. Unplugging the light removes the "USB Serial" entries from `ioreg`.

| Field         | Value                                  |
|---------------|----------------------------------------|
| Chip          | CH340 (QinHeng Electronics)            |
| VID           | 0x1A86 (6790)                          |
| PID           | 0x7523 (29987)                         |
| USB Class     | CDC / Serial                           |
| Device path   | `/dev/cu.usbserial-11220`              |
| Driver        | `com.apple.DriverKit.AppleUSBCHCOM`    |

This is the simplest scenario — the light appears as a standard serial port.
Communication is done by opening the device file and reading/writing bytes
directly. No special USB HID or custom driver needed. Use `pyserial` (Python)
or any serial library.

---

## Existing Open-Source Projects

All existing projects use **BLE** (Bluetooth Low Energy), not USB. No one has
publicly reverse-engineered the USB protocol for any Neewer light.

| Project | Language | Protocol | Link |
|---------|----------|----------|------|
| NeewerLite | Swift (macOS) | BLE (CoreBluetooth) | [keefo/NeewerLite](https://github.com/keefo/NeewerLite) |
| NeewerLite-Python | Python | BLE (Bleak) | [taburineagle/NeewerLite-Python](https://github.com/taburineagle/NeewerLite-Python) |
| neewerctl | Rust | BLE (btleplug) | [ratmice/neewerctl](https://github.com/ratmice/neewerctl) |
| neewer-controller | C++ (ESP32) | BLE | [DanielBaulig/neewer-controller](https://github.com/DanielBaulig/neewer-controller) |
| neewer-gl1 | Node.js | WiFi/UDP | [braintapper/neewer-gl1](https://github.com/braintapper/neewer-gl1) |

---

## BLE Protocol (Well Documented)

The BLE protocol has been thoroughly reverse-engineered by the community and is
the foundation of every open-source project. It's relevant because the USB
protocol likely shares the same command structure internally.

### BLE UUIDs
- Service: `69400001-B5A3-F393-E0A9-E50E24DCCA99`
- Write Characteristic: `69400002-B5A3-F393-E0A9-E50E24DCCA99`
- Notify Characteristic: `69400003-B5A3-F393-E0A9-E50E24DCCA99`

### Command Format
All commands follow:
```
[0x78] [command_tag] [payload_length] [payload...] [checksum]
```
- Prefix: always `0x78`
- Checksum: `sum(all_preceding_bytes) & 0xFF`

### Known Commands

**Power:**
```
On:  78 81 01 01 [checksum]
Off: 78 81 01 02 [checksum]
```

**CCT Mode (brightness + color temperature):**
```
78 87 02 [brightness 0x00-0x64] [cct_value] [checksum]
```
- Brightness: 0-100 (0x00-0x64)
- CCT value: 0x20 (3200K) to 0x38 (5600K)
- Formula: `((temp_K - 3200) / 2400) * (0x38 - 0x20) + 0x20`

**HSI/RGB Mode (hue + saturation + intensity):**
```
78 86 04 [hue_lo] [hue_hi] [saturation] [brightness] [checksum]
```
- Hue: 0-360 degrees, 16-bit little-endian
- Saturation: 0-100 (0x00-0x64)
- Brightness: 0-100 (0x00-0x64)

**Scene/Effect Mode:**
```
78 88 02 [brightness] [scene_id] [checksum]
```
Scene IDs: 1=Squad Car, 2=Ambulance, 3=Fire Engine, 4=Fireworks, 5=Party,
6=Candle, 7=Lightning, 8=Paparazzi, 9=Screen

### Newer "MAC-addressed" Command Variants
Some newer lights use an extended format with a 6-byte MAC address:
```
78 8D 08 [6-byte MAC] 81 [01=on/02=off] [checksum]   (power)
78 8E [len] [6-byte MAC] 87 [brightness] [cct] [checksum]  (CCT)
78 8F [len] [6-byte MAC] 86 [hue_lo] [hue_hi] [sat] [bri] 00 [checksum]  (HSI)
```

---

## USB Architecture (Dual-Channel)

The PL81-Pro presents as a **composite USB device** with two interfaces:

| Interface        | Chip    | VID:PID       | Role                    |
|------------------|---------|---------------|-------------------------|
| HID (vendor)     | Realtek | 0x0BDA:0x1100 | **Commands** (host→light) |
| Serial (CDC)     | CH340   | 0x1A86:0x7523 | **Status** (light→host)   |

This was confirmed by:
- `fs_usage` shows the Neewer app **never reads/writes** the serial port file
- App binary contains `USBHIDDevice`, `IOHIDDeviceSetReport`, `BT_Send_USB_Data:`
- App uses ORSSerialPort for receiving status only
- Plug/unplug: Realtek HID stays (part of USB hub), CH340 disappears

**CORRECTION**: The Realtek HID (VID 0x0BDA) is part of the USB **hub/dock**,
not the light itself (it remained when the light was unplugged). The Neewer app
uses this HID interface for communication — the light's firmware routes through
the hub's HID chip.

### HID Report Descriptor
```
06 DA FF    Usage Page (0xFFDA, vendor-specific)
09 DA       Usage (0xDA)
A1 01       Collection (Application)
  15 80     Logical Min (-128)
  25 7F     Logical Max (127)
  75 08     Report Size (8 bits)
  95 C0     Report Count (192)
  09 D1     Usage (0xD1)
  91 02     Output (192 bytes, no report ID)
  75 08     Report Size (8 bits)
  95 C0     Report Count (192)
  09 D2     Usage (0xD2)
  81 02     Input (192 bytes, no report ID)
C0          End Collection
```

- Output reports: **192 bytes**, report ID 0, usage 0xD1
- Input reports: **192 bytes**, report ID 0, usage 0xD2
- No feature reports

### macOS Permission Requirement
Writing to the HID device requires **Input Monitoring** permission.
`IOHIDDeviceSetReport` returns `0xe0005000` without it.
The NEEWER Control Center app has this via App Store entitlements.

**Fix:** System Settings → Privacy & Security → Input Monitoring → add Terminal

---

## Serial Status Protocol (Light → Host)

### Connection Parameters
- **Baud rate: 115200**
- 8N1 (8 data bits, no parity, 1 stop bit)
- Device: `/dev/cu.usbserial-*`
- Library: `pyserial`

### Packet Format
```
[0x3A] [command_tag] [payload_length] [payload...] [checksum]
```
- Prefix: always `0x3A` (ASCII `:`)
- Checksum: `sum(all_preceding_bytes) & 0xFF`

### Captured: Light → Host Status Reports
The light sends 8-byte status packets **unprompted** when its state changes
(e.g. physical knob turns). No polling or handshake needed.

```
3a 02 03 01 32 09 00 7b   brightness=50, cct=0x09
3a 02 03 01 0f 09 00 58   brightness=15, cct=0x09
3a 02 03 01 23 09 00 6c   brightness=35, cct=0x09
3a 02 03 01 07 09 00 50   brightness=7,  cct=0x09
```

Decoded structure:
| Byte | Value  | Meaning                              |
|------|--------|--------------------------------------|
| 0    | `0x3A` | Prefix                               |
| 1    | `0x02` | Command tag (status report)          |
| 2    | `0x03` | Payload length (3 bytes)             |
| 3    | `0x01` | Mode (0x01 = CCT mode?)              |
| 4    | varies | Brightness (0-100 decimal)           |
| 5    | `0x09` | Color temperature (encoding TBD)     |
| 6    | `0x00` | Unknown / padding                    |
| 7    | varies | Checksum: `sum(bytes 0-6) & 0xFF`    |

### CCT Encoding
App shows 7000K when byte 5 = `0x09`. The PL81 Pro range is 3200K-7000K.
Encoding is TBD — may be an index or different scale than BLE (0x20-0x38).

---

## Key Unknowns

1. ~~**Which USB device is the light?**~~ **RESOLVED** — dual: HID + serial
2. ~~**HID vs Serial vs Custom?**~~ **RESOLVED** — HID for commands, serial for status
3. ~~**Baud rate**~~ **RESOLVED** — 115200
4. ~~**Does the light send state back?**~~ **YES** — 8-byte serial status packets
5. **HID command format** — need Input Monitoring permission to test
6. **Does HID use BLE protocol (0x78) or USB protocol (0x3A)?** — TBD
7. **CCT byte encoding** — `0x09` = 7000K, but formula unknown
8. **HID checksum** — binary has `checkSumUsbWithData:dataID:` (may differ from BLE)
