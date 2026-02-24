# Neewer PL81-Pro USB Control — Plan

## Phase 1: Device Identification — DONE

- [x] Plug/unplug test confirmed the light is the **CH340 USB Serial** device
- [x] VID 0x1A86, PID 0x7523, device path `/dev/cu.usbserial-11220`
- [x] Communication method: **serial port** (pyserial)

## Phase 2: Traffic Capture

Since it's a serial device, we can use a `socat` proxy to MITM between the
NEEWER Control Center app and the light. This logs every byte in both
directions.

**Setup:**
```bash
# Rename the real device, create a proxy that the Neewer app connects to
socat -x -v /dev/cu.usbserial-11220,raw,echo=0 PTY,link=/tmp/neewer-proxy,raw,echo=0
```
Then point the Neewer app at `/tmp/neewer-proxy` (may need to symlink over the
original device path).

**Alternative:** Write a simple Python serial sniffer that opens the port,
tries known BLE commands at various baud rates, and logs any responses.

**Captures needed:**
- [ ] Determine baud rate (try 9600, 115200, 256000 with the Neewer app)
- [ ] Capture: power on / power off
- [ ] Capture: brightness sweep 0% → 100%
- [ ] Capture: CCT sweep 3200K → 5600K
- [ ] Capture: RGB/HSI mode changes
- [ ] Capture: scene/effect activations
- [ ] Save captures to `captures/`

## Phase 3: Protocol Analysis

- [ ] Decode captured byte sequences
- [ ] Compare against known BLE protocol (`0x78` prefix, checksum)
- [ ] Document any framing, handshake, or initialization sequence
- [ ] Document any response/feedback from light → host
- [ ] Write up complete protocol spec in PROTOCOL.md

## Phase 4: Proof of Concept

- [ ] Write a minimal Python script that opens the serial port and sends
      power on/off using the discovered protocol
- [ ] Extend to brightness + CCT control
- [ ] Extend to HSI/RGB control
- [ ] Extend to scene/effect control
- [ ] Verify reliability (no dropped commands, correct state)

## Phase 5: CLI Tool

- [ ] Build a proper CLI with argparse or click
- [ ] Commands: `power`, `brightness`, `cct`, `rgb`, `scene`, `status`
- [ ] Auto-detect the light's serial port path
- [ ] Add preset support (save/recall favorite settings)

## Phase 6: Nice-to-Haves (Later)

- [ ] Web UI or TUI for interactive control
- [ ] Stream Deck integration
- [ ] Home Assistant integration
- [ ] Shortcuts/automation support
- [ ] Multi-light support
