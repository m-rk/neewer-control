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

## USB Architecture — Serial Commands (SOLVED 2026-02-24)

**Commands go through SERIAL, not HID.** The missing piece was the
**16-bit big-endian checksum** (decoded from the app binary). All previous
serial probes used 1-byte checksums and failed.

| Channel          | Chip    | VID:PID       | Role                           |
|------------------|---------|---------------|--------------------------------|
| Serial (CDC)     | CH340   | 0x1A86:0x7523 | **Commands AND status** (bidir)|
| HID (vendor)     | Realtek | 0x0BDA:0x1100 | Hub management only            |

### Evidence

**CCT commands work via serial with 16-bit checksum:**
```
Sent: 3a 02 03 01 64 09 00 ad   → light changed to 100% brightness
Resp: 3a 02 03 01 64 09 00 ad   → light echoes command back

Sent: 3a 02 03 01 0a 09 00 53   → light changed to 10% brightness
Resp: 3a 02 03 01 0a 09 00 53   → confirmed
```

**1-byte checksum does NOT work** — same format, same data, but with
7-byte packet and 1-byte checksum: no response, no light change.

**HID is hub-only:** The Realtek HID device stays present when the light is
unplugged. Only tag 0x06 is accepted (no STALL), but produces no light change.
It's the Realtek hub's own management interface, not the light's.

### Why Previous Serial Probes Failed
We tested 100+ serial command formats with **1-byte checksums** — all failed.
The correct format uses a **16-bit big-endian checksum**, which was only
discovered by disassembling the app binary's `checkSumWithUsbData:` method.

### HID Details

The Realtek HID device (VID 0x0BDA, PID 0x1100) is physically part of the USB
hub/dock (it stays present when the light is unplugged). The hub routes HID
commands to the light's internal controller.

**HID Report Descriptor:**
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

### macOS Permission / USB Stall Issue

`IOHIDDeviceSetReport` returns `0xe0005000` which is **`kUSBHostReturnPipeStalled`**
(USB endpoint STALL handshake), NOT a TCC permission error. TCC logs confirm
`authValue=2` (ALLOWED) for our processes. The device opens fine but rejects
the actual report write at the USB protocol level.

Possible causes:
- **Wrong command format/checksum** — the device validates and STALLs on bad data
- **Missing initialization handshake** — may need to send/receive something first
- **Report type mismatch** — device may expect Feature or Input report type
- **Missing serial channel interaction** — app uses both channels simultaneously

The NEEWER Control Center app has entitlements:
- `com.apple.security.device.usb`
- `com.apple.security.device.serial`
- `com.apple.security.app-sandbox`
- Signed by team U3W63A85HG (proper Developer ID)

### Workarounds to Try (from Apple Forums / hidapi issues)

1. **Use `kIOHIDReportTypeInput` (0)** instead of `kIOHIDReportTypeOutput` (1)
   — some vendor-specific devices only accept via the input code path
2. **Use Feature reports** — sends via USB control transfer (endpoint 0) instead
   of interrupt OUT. Descriptor has no feature reports, but worth testing.
3. **Register an input report callback** to drain responses before writing
4. **Try `hidapitester`** CLI tool (github.com/todbot/hidapitester)
5. **Try Python `hid` (cython-hidapi)** — note: `hid.write()` prepends report ID
   byte (0x00), so send 193 bytes total (1 + 192)

---

## Serial Command & Status Protocol (WORKING)

### Connection Parameters
- **Baud rate: 115200**
- 8N1 (8 data bits, no parity, 1 stop bit)
- Device: `/dev/cu.usbserial-*`
- Library: `pyserial`

### Packet Format
```
[0x3A] [tag] [payload_length] [payload...] [checksum_hi] [checksum_lo]
```
- Prefix: always `0x3A` (ASCII `:`)
- **Checksum: 16-bit big-endian sum** of all preceding bytes
- Total packet size: variable (6-8+ bytes depending on command)
- Light echoes back the exact command bytes as acknowledgment

### Working Commands (Confirmed)

**CCT Mode (tag 0x02) — WORKING:**
```
3A 02 03 01 [brightness] [temperature] [cs_hi] [cs_lo]
```
- brightness: 0-100 (0x00-0x64)
- temperature: 0x09 = 7000K (encoding TBD for other values)
- Total: 8 bytes
- Light changes immediately AND echoes the command back

**Power ON/OFF (tag 0x06) — sends but no response:**
```
3A 06 01 01 [cs_hi] [cs_lo]    (ON — 6 bytes, no light change)
3A 06 01 02 [cs_hi] [cs_lo]    (OFF — 6 bytes, no light change)
```
- May not apply to PL81-Pro (perhaps use brightness=0 to "turn off"?)
- Or may need 8-byte fixed length

### Status Packets (Light → Host, unprompted)
The light sends status when its physical controls are used:
```
3a 02 03 01 32 09 00 7b   brightness=50, cct=0x09
3a 02 03 01 0f 09 00 58   brightness=15, cct=0x09
```
Same format as commands — bidirectional protocol.

### Decoded Structure
| Byte | Value  | Meaning                              |
|------|--------|--------------------------------------|
| 0    | `0x3A` | Prefix                               |
| 1    | `0x02` | Tag (0x02 = CCT mode)                |
| 2    | `0x03` | Payload length (3 bytes)             |
| 3    | `0x01` | Mode (0x01 = CCT)                    |
| 4    | varies | Brightness (0-100 decimal)           |
| 5    | `0x09` | Color temperature (see below)        |
| 6-7  | varies | 16-bit big-endian checksum           |

### CCT Temperature Encoding
- PL81 Pro range: 3200K-7000K
- App shows 7000K when byte 5 = `0x09`
- Temperature byte accepts values 0x00-0x3F (all produce echo ack)
- Temp scan confirmed all values 0x00-0x3F are accepted by the light
- Exact K mapping TBD — need to cross-reference with light's display

---

## HID Command Protocol (Host → Light) — DECODED via Disassembly

**Source:** x86_64 disassembly of NEEWER Control Center.app binary (otool -tV).
The protocol was fully decoded from `publishUsb*` methods and `checkSumWithUsbData:`.

### USB Command Format
```
[0x3A] [tag] [payload_length] [payload...] [checksum_hi] [checksum_lo]
```
- Prefix: **`0x3A`** (same as serial status — NOT 0x78 like BLE)
- Checksum: **16-bit big-endian sum** of all preceding bytes (2 bytes, NOT 1 like BLE)
- Commands are sent as **192-byte HID output reports** (zero-padded)
- Report type: `kIOHIDReportTypeOutput` (1)
- Report ID: **0**

### Checksum Algorithm (`checkSumWithUsbData:`)
```python
def usb_checksum(data: bytes) -> bytes:
    """16-bit sum of all bytes, returned as 2 bytes big-endian."""
    s = sum(data) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])
```
Decoded from x86_64 asm: the function sums all bytes into a 16-bit value, then
uses `rolw $0x8` (rotate word left 8 bits = byte-swap) to convert to big-endian,
and appends 2 bytes to the data.

### `checkSumUsbWithData:dataID:` — Wrapper
The `dataID` parameter controls a branch:
- **If `dataID == 5`**: Prepends a 1-byte `isOpen` status flag + 1-byte `isOpen` value,
  then creates a 3-byte header `[0x3A] [dataID] [data.length]`, appends the data,
  and calls `checkSumWithUsbData:` on the combined result.
- **Otherwise**: Creates header `[0x3A] [dataID] [data.length]`, appends data,
  calls `checkSumWithUsbData:`.

### Known USB Commands (from disassembly)

**Power On/Off (`publishUsbTurnOn:`):**
```
3A 06 01 [01=on / 02=off] [checksum_hi] [checksum_lo]
```
- Tag: `0x06`
- Payload length: `0x01`
- Payload: `0x01` = on, `0x02` = off

**Power On with CCT (`publishUsbTurnOn:brightness:temperature:`):**
```
3A 02 03 [01=on / 02=off] [brightness] [temperature] [checksum_hi] [checksum_lo]
```
- Tag: `0x02`
- Payload length: `0x03`

**CCT Mode (`publishUsbCCTWithBrightness:temperature:`):**
```
3A 02 03 01 [brightness 0-100] [temperature] [checksum_hi] [checksum_lo]
```
- Tag: `0x02`
- Payload length: `0x03`
- Mode byte: `0x01` (hardcoded)
- This matches the serial status format exactly (except checksum is 2 bytes)

**HSI Mode (`publishUsbHSIWithBrightness:hue:sat:`):**
Built via `checkSumUsbWithData:dataID:4`:
```
3A 04 04 [hue_lo] [hue_hi] [saturation] [brightness] [cs_hi] [cs_lo]
```
- Tag: `0x04`, payload length: `0x04`
- hue_hi = 1 if hue >= 256, else 0 (from `cmpq $0x100` + `setge`)
- Saturation: 0-100, Brightness: 0-100

**Scene Mode (`publishUsbSceneWithType:sceneData:`):**
Delegates to `publishSceneWithType:sceneData:` after setting `isUsb=1`.
The generic scene method handles the framing (likely same 0x3A format).

### HID SetReport Details
From `setReport:data:length:reportID:` disassembly:
- Calls `IOHIDDeviceSetReport(deviceRef, reportType, reportID, data, length)`
- Report type passed as parameter (callers pass `1` = kIOHIDReportTypeOutput)
- Uses `outReprotID` (typo in app — "Reprot" = "Report") for report ID
- The `outReprotID` is set dynamically to `data.length` before sending

### Data Flow (from disassembly)
1. `publishUsb*` builds a command as NSMutableData (e.g., `3A 02 03 01 64 09`)
2. Calls `checkSumWithUsbData:` which appends 2-byte big-endian checksum
   → e.g., `3A 02 03 01 64 09 00 AD` (8 bytes)
3. Returns the complete NSData to caller
4. Caller (BT_Send_USB_Data or equivalent) prepends 1-byte length:
   → e.g., `08 3A 02 03 01 64 09 00 AD` (9 bytes)
5. Sets `outReprotID` = original data length (8 in this example)
6. `setReport:data:length:reportID:` sends via IOHIDDeviceSetReport
   → `IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, 8, data, 9)`
   → reportID = data length, report type = Output (1)

### Example: CCT 100% brightness, 7000K (temp=0x09)
```
Payload:  3A 02 03 01 64 09
Checksum: sum(3A+02+03+01+64+09) = 0x00AD → 00 AD
With cs:  3A 02 03 01 64 09 00 AD  (8 bytes)
Prepend:  08 3A 02 03 01 64 09 00 AD  (9 bytes)
SendAs:   IOHIDDeviceSetReport(dev, Output, reportID=8, data, 9)
```

### HID Access: cython-hidapi Works (2026-02-24)

cython-hidapi (`pip3 install hidapi`) can enumerate and open the Realtek HID
device **without** needing Input Monitoring permission. Raw IOKit requires it.

**Two device instances** are enumerated:
- `DevSrvsID:4296176640` (usage_page=0xFFDA)
- `DevSrvsID:4296214651` (usage_page=0xFFDA)

### Write Results: Only Tag 0x06 Accepted

Tested all tags 0x00-0x0F via `hid.write()`:
- **Tag 0x06**: `wrote 193` (accepted, no STALL) — any payload length works
- **All other tags**: `wrote -1` (0xE0005000 = USB pipe STALL)

The Realtek firmware validates incoming reports and STALLs on unrecognized tags.
The STALL is not persistent — subsequent tag-0x06 writes still succeed.

**But the light doesn't respond** to any writes (even successful ones).
Power ON/OFF with tag 0x06 doesn't turn the light on or off.
This suggests:
1. We may be writing to the wrong device instance (two were enumerated)
2. Tag 0x06 might be a Realtek hub-level command, not forwarded to the light
3. An initialization handshake may be required
4. The app may use the other device instance or a different open mode

### Critical Insight: Why Previous Probes Failed
Our serial probes used the right format (`3A 02 03 01 [bri] [cct] 00 [1-byte-cs]`)
but with a **1-byte checksum** instead of the correct **2-byte big-endian checksum**.
Also, serial is the wrong channel — commands must go through HID.

---

## Third-Party Research (2026-02-24)

### No USB control projects exist
Every third-party Neewer project uses BLE only. This project would be the
first public USB control implementation.

### Neewer GL1 WiFi Protocol (structural parallel)
The [neewer-gl1](https://github.com/braintapper/neewer-gl1) project shows Neewer
uses **different prefixes per transport** but the **same underlying structure**:
- WiFi/UDP prefix: `0x80`
- BLE prefix: `0x78`
- Serial status prefix: `0x3A`
- USB HID prefix: **unknown** (could be 0x78, 0x80, 0x3A, or new)

WiFi command: `80 05 03 02 [brightness] [temp/100] [checksum]`
WiFi requires an initialization handshake before commands work.

### NEEWER Control Center app binary analysis
Key Objective-C methods found:
- `checkSumUsbWithData:dataID:` — USB checksum differs from BLE (extra `dataID` param)
- `checkSumBleWithData:dataID:` — BLE checksum for comparison
- `BT_Send_USB_Data:` — sends BLE-format commands over USB
- `NWInstructionManager` — command construction
- `NWUSBPortManager` — USB port management
- Uses `ORSSerialPort` framework for serial communication

The `dataID` parameter in the checksum function is critical — could be:
- A packet sequence number
- The HID report ID (0)
- A device-specific identifier
- A constant like the usage value (0xD1)

### Decompilation opportunity
The app is native Objective-C (not Electron). Tools to extract protocol:
- `class-dump` — extract all ObjC class/method signatures
- Ghidra/Hopper — decompile `checkSumUsbWithData:dataID:` to see algorithm
- Look at `BT_Send_USB_Data:` to see exact framing

---

## Resolved & Remaining Unknowns

### Resolved
1. ~~**Which USB device is the light?**~~ Serial (CH340) for commands, HID (Realtek) is hub only
2. ~~**Command channel**~~ **SERIAL** — not HID! (previous dual-channel theory was wrong)
3. ~~**Baud rate**~~ 115200, 8N1
4. ~~**Status feedback**~~ Light echoes commands AND sends unprompted status on knob turns
5. ~~**Command format**~~ `3A [tag] [len] [payload] [16-bit big-endian checksum]`
6. ~~**Checksum**~~ 16-bit big-endian sum (the missing piece — 1-byte never worked)
7. ~~**CCT control**~~ `3A 02 03 01 [bri 0-100] [temp] [cs_hi] [cs_lo]` — WORKING
8. ~~**HID 0xe0005000**~~ Irrelevant — HID is hub management, not light control
9. ~~**Serial writes from app**~~ They ARE the commands (not acks/keepalives)

10. ~~**HSI mode**~~ Not supported — PL81-Pro is bi-color (CCT only), no RGB LEDs. Tag 0x04 commands send without error but produce no echo and no light change.

### Remaining
1. **CCT temperature encoding** — 0x09 = 7000K, full mapping TBD
2. **Power ON/OFF** — tag 0x06 accepted but no light change; may not apply to PL81-Pro
3. **Scene/effect mode** — untested over serial
