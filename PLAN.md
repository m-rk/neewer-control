# Neewer PL81-Pro USB Control — Plan

## Phase 1: Device Identification

- [ ] Unplug PL81 Pro, run `ioreg -r -c IOUSBHostDevice` or `system_profiler SPUSBDataType`
- [ ] Plug it back in, run the same command
- [ ] Diff results to identify exact VID, PID, and USB class
- [ ] Determine if it's HID, CDC/Serial, or custom USB class
- [ ] Document findings in RESEARCH.md

## Phase 2: Traffic Capture

- [ ] Install NEEWER Control Center (Mac App Store) if not already installed
- [ ] Set up traffic capture method:
  - If serial: `socat` proxy or `dtrace` on the device file
  - If HID: USB Prober via Xcode Instruments or hidapi enumeration
- [ ] Capture baseline: power on, power off
- [ ] Capture brightness sweep: 0% → 100%
- [ ] Capture CCT sweep: 3200K → 5600K
- [ ] Capture RGB/HSI mode changes
- [ ] Capture scene/effect activations
- [ ] Save all captures to `captures/` directory

## Phase 3: Protocol Analysis

- [ ] Decode captured byte sequences
- [ ] Compare against known BLE protocol (`0x78` prefix, checksum)
- [ ] Document any framing, handshake, or initialization sequence
- [ ] Document any response/feedback protocol from light → host
- [ ] Write up complete protocol spec in PROTOCOL.md

## Phase 4: Proof of Concept

- [ ] Write a minimal Python script that sends power on/off
- [ ] Extend to brightness + CCT control
- [ ] Extend to HSI/RGB control
- [ ] Extend to scene/effect control
- [ ] Verify reliability (no dropped commands, correct state)

## Phase 5: CLI Tool

- [ ] Build a proper CLI with argparse or click
- [ ] Commands: `power`, `brightness`, `cct`, `rgb`, `scene`, `status`
- [ ] Auto-detect the light's serial/HID path
- [ ] Add preset support (save/recall favorite settings)

## Phase 6: Nice-to-Haves (Later)

- [ ] Web UI or TUI for interactive control
- [ ] Stream Deck integration
- [ ] Home Assistant integration
- [ ] Shortcuts/automation support
- [ ] Multi-light support
