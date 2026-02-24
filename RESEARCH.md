# Neewer PL81-Pro USB Control — Research

## Goal

Replace the proprietary NEEWER Control Center desktop app with a custom solution
for controlling the Neewer PL81-Pro-1260740 panel light via USB-C on macOS.

---

## USB Device Detection (2026-02-24)

No device explicitly labeled "Neewer" was found in the USB device tree. Devices
detected on this system:

| Device              | VID (dec) | PID (dec) | Notes                          |
|---------------------|-----------|-----------|--------------------------------|
| Generic USB2.1 Hub  | 3034      | 21521     | Realtek hub chip               |
| Realtek HID Device  | 3034      | 4352      | Could be Neewer, generic name  |
| USB Serial (CH340)  | 6790      | 29987     | `/dev/cu.usbserial-11220`      |
| daskeyboard         | 1241      | 8211      | Keyboard                       |
| OBSBOT Tiny 2       | 13668     | 65272     | Webcam                         |
| Stream Deck Plus    | 4057      | 132       | Elgato                         |
| fifine Microphone   | 12610     | 1672      | Microphone                     |

**Two candidates for the Neewer light:**

1. **Realtek HID Device** (VID 0x0BDA / 3034, PID 0x1100 / 4352) — Shows as a
   generic HID device. Could be the light presenting as USB HID.
2. **CH340 USB Serial** (VID 0x1A86 / 6790, PID 0x7523 / 29987) — CH340 chips
   are extremely common in Chinese electronics. The light could use a serial
   protocol over this chip.

**Next step:** Unplug the light and re-enumerate USB to identify which device
disappears — that's the Neewer.

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

## macOS Libraries for USB Communication

### If the light is USB HID:
- **hidapi** (C, with Python bindings) — Best option. Uses IOHIDManager
  natively on macOS. No kernel driver conflicts. `pip install hidapi`
- **node-hid** (Node.js) — Wrapper around hidapi. `npm install node-hid`
- **pyusb** (Python) — Lower-level, but macOS kernel claims HID devices,
  causing access issues. Prefer hidapi.

### If the light is USB Serial (CH340):
- **pyserial** (Python) — `pip install pyserial`. Open `/dev/cu.usbserial-*`
  and read/write bytes directly. Simplest approach.
- **serialport** (Node.js) — `npm install serialport`
- Native: just `open()` the device file and `read()`/`write()`

### For BLE (alternative/fallback approach):
- **Bleak** (Python) — Cross-platform, mature. `pip install bleak`
- **CoreBluetooth** (Swift) — Native macOS, what NeewerLite uses.

---

## USB Reverse Engineering Strategy

### Phase 1: Identify the Device
1. Unplug the PL81 Pro, enumerate USB devices
2. Plug it back in, enumerate again
3. Diff the results to find the exact VID/PID and USB class
4. Check if it appears as HID, CDC/Serial, or custom USB class

### Phase 2: Sniff the Protocol
1. Install NEEWER Control Center from the Mac App Store
2. Set up USB packet capture (options below)
3. Perform simple operations: power on/off, brightness up/down, change CCT
4. Capture and analyze the packets

**USB capture options on macOS:**
- **Wireshark + USBPcap**: Limited on macOS, better on Linux
- **USB Prober** (Xcode instruments): Apple's USB debugging tool
- **PacketLogger**: Apple's Bluetooth packet logger (if BLE-over-USB)
- **strace/dtrace on the serial port**: If it's a CH340 serial device, you can
  monitor reads/writes on `/dev/cu.usbserial-*`
- **socat proxy**: Create a serial proxy that logs all traffic between the
  Neewer app and the device

### Phase 3: Decode the Commands
- Compare captured bytes against the known BLE command structure
- The `0x78` prefix and checksum algorithm are likely identical
- Map each UI action to a byte sequence

### Phase 4: Build the Tool
- Start with a simple Python CLI using pyserial or hidapi
- Implement core commands: power, brightness, CCT, HSI/RGB
- Add a TUI or web UI later if desired

---

## Key Unknowns

1. **Which USB device is the light?** Need to plug/unplug test
2. **HID vs Serial vs Custom?** Determines which library to use
3. **Does USB use same protocol as BLE?** Likely, but unconfirmed
4. **Baud rate** (if serial): Common candidates are 9600, 115200, 256000
5. **Any handshake required?** The WiFi protocol needs a 3-packet handshake;
   USB might need something similar
6. **Does the light send state back?** BLE has a notify characteristic; USB
   might have a similar feedback mechanism
