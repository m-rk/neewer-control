#!/usr/bin/env python3
"""
Serial probe v2 — tries DTR/RTS signal combinations and 0x3A 0x01 command
prefix discovered in the Neewer binary.

Key findings from binary analysis:
  - Light sends status with prefix 3A 02 (3a 02 03 01 XX YY 00 CS)
  - Binary contains 3A 01 pattern — likely the command prefix
  - DTR/RTS hardware signals may be required for the light to accept commands
"""

import glob
import sys
import time

import serial


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_cmd(prefix: int, tag: int, payload: bytes) -> bytes:
    frame = bytes([prefix, tag, len(payload)]) + payload
    return frame + bytes([checksum(frame)])


def find_serial_port() -> str:
    candidates = glob.glob("/dev/cu.usbserial-*")
    if not candidates:
        print("ERROR: No serial port found")
        sys.exit(1)
    return candidates[0]


def send_and_listen(ser: serial.Serial, label: str, cmd: bytes, wait: float = 1.0):
    hex_str = cmd.hex(" ")
    print(f"  >> {label:<45s}  [{hex_str}]")
    ser.write(cmd)
    ser.flush()
    time.sleep(0.1)
    start = time.time()
    while time.time() - start < wait:
        data = ser.read(64)
        if data:
            print(f"  << RESPONSE ({len(data)} bytes): [{data.hex(' ')}]")
        time.sleep(0.05)


def drain(ser: serial.Serial, timeout: float = 1.0):
    """Drain any pending data."""
    start = time.time()
    count = 0
    while time.time() - start < timeout:
        data = ser.read(256)
        if data:
            count += len(data)
        time.sleep(0.05)
    if count:
        print(f"  (drained {count} bytes)")


def test_serial_config(port: str, dtr: bool, rts: bool, label: str):
    """Test commands with specific DTR/RTS settings."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  DTR={'HIGH' if dtr else 'LOW'}  RTS={'HIGH' if rts else 'LOW'}")
    print(f"{'='*60}\n")

    ser = serial.Serial(
        port=port,
        baudrate=115200,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0,
        write_timeout=1,
        dsrdtr=False,
        rtscts=False,
    )

    # Set DTR and RTS
    ser.dtr = dtr
    ser.rts = rts
    time.sleep(0.5)  # Give the device time to react to signal changes

    ser.reset_input_buffer()
    ser.reset_output_buffer()

    drain(ser, 0.5)

    # Test commands with 3A 01 prefix (command format from binary)
    cmds = [
        # 3A 01 — suspected command prefix with 3 payload bytes
        ("CCT 100% warm (3A 01 03)",  build_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09]))),
        ("CCT 10%  warm (3A 01 03)",  build_cmd(0x3A, 0x01, bytes([0x01, 0x0A, 0x09]))),

        # 3A 01 with trailing 0x00 (matching 8-byte status packet format)
        ("CCT 100% (3A 01 04 +00)",   build_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09, 0x00]))),
        ("CCT 10%  (3A 01 04 +00)",   build_cmd(0x3A, 0x01, bytes([0x01, 0x0A, 0x09, 0x00]))),

        # Power with 3A 01
        ("Power ON  (3A 01)",         build_cmd(0x3A, 0x01, bytes([0x01]))),
        ("Power OFF (3A 01)",         build_cmd(0x3A, 0x01, bytes([0x02]))),

        # BLE-style tags with 3A prefix
        ("Power ON  (3A 81)",         build_cmd(0x3A, 0x81, bytes([0x01]))),
        ("CCT 100% (3A 87)",          build_cmd(0x3A, 0x87, bytes([0x64, 0x2C]))),
        ("CCT 10%  (3A 87)",          build_cmd(0x3A, 0x87, bytes([0x0A, 0x2C]))),

        # Original BLE commands (0x78)
        ("Power ON  (78 81)",         build_cmd(0x78, 0x81, bytes([0x01]))),
        ("CCT 100% (78 87)",          build_cmd(0x78, 0x87, bytes([0x64, 0x2C]))),
        ("CCT 10%  (78 87)",          build_cmd(0x78, 0x87, bytes([0x0A, 0x2C]))),
    ]

    for label, cmd in cmds:
        send_and_listen(ser, label, cmd, wait=0.5)

    ser.close()


def test_parity_stopbits(port: str):
    """Try different parity and stop bit settings."""
    configs = [
        (serial.PARITY_EVEN, serial.STOPBITS_ONE, "8E1"),
        (serial.PARITY_ODD, serial.STOPBITS_ONE, "8O1"),
        (serial.PARITY_NONE, serial.STOPBITS_TWO, "8N2"),
    ]

    for parity, stopbits, name in configs:
        print(f"\n{'='*60}")
        print(f"  Config: {name} (DTR=HIGH, RTS=HIGH)")
        print(f"{'='*60}\n")

        try:
            ser = serial.Serial(
                port=port,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=parity,
                stopbits=stopbits,
                timeout=0,
                write_timeout=1,
            )
            ser.dtr = True
            ser.rts = True
            time.sleep(0.3)
            ser.reset_input_buffer()

            # Quick test: CCT 100% with BLE format
            send_and_listen(ser, "CCT 100% (78 87)", build_cmd(0x78, 0x87, bytes([0x64, 0x2C])))
            send_and_listen(ser, "CCT 10%  (78 87)", build_cmd(0x78, 0x87, bytes([0x0A, 0x2C])))
            send_and_listen(ser, "CCT 100% (3A 01)", build_cmd(0x3A, 0x01, bytes([0x01, 0x64, 0x09])))
            send_and_listen(ser, "CCT 10%  (3A 01)", build_cmd(0x3A, 0x01, bytes([0x01, 0x0A, 0x09])))

            ser.close()
        except Exception as e:
            print(f"  Error: {e}")


def main():
    port = find_serial_port()
    print(f"Neewer PL81-Pro Serial Probe v2")
    print(f"Device: {port}")
    print()

    # Test all DTR/RTS combinations
    test_serial_config(port, dtr=False, rts=False, label="DTR=LOW  RTS=LOW")
    input("React? Enter to continue...")

    test_serial_config(port, dtr=True,  rts=False, label="DTR=HIGH RTS=LOW")
    input("React? Enter to continue...")

    test_serial_config(port, dtr=False, rts=True,  label="DTR=LOW  RTS=HIGH")
    input("React? Enter to continue...")

    test_serial_config(port, dtr=True,  rts=True,  label="DTR=HIGH RTS=HIGH")
    input("React? Enter to continue...")

    # Test different serial configurations
    test_parity_stopbits(port)

    print("\nDone.")


if __name__ == "__main__":
    main()
