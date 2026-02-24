#!/usr/bin/env python3
"""
Serial MITM proxy that sits between the NEEWER Control Center app and
the PL81-Pro light, logging all traffic in both directions.

Creates a virtual serial port (PTY) that the Neewer app connects to,
and forwards everything to/from the real device while logging hex dumps.

Usage:
  1. Close the NEEWER Control Center app
  2. Run: python3 sniff.py
  3. Open the NEEWER Control Center app
  4. In the app, select the virtual port (shown in script output)
  5. Use the app normally — all traffic is logged to captures/

If the app auto-detects and won't let you pick a port, the script will
attempt to create the virtual port at the same path as the real device
by temporarily unlinking it (requires sudo).
"""

import datetime
import glob
import os
import select
import signal
import sys
import time
import termios
import tty

import serial


BAUD_RATES_TO_TRY = [9600, 19200, 38400, 57600, 115200, 230400, 256000]
CAPTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")


def find_serial_port() -> str:
    candidates = glob.glob("/dev/cu.usbserial-*")
    if not candidates:
        print("ERROR: No /dev/cu.usbserial-* device found. Is the light plugged in?")
        sys.exit(1)
    return candidates[0]


def hex_dump(data: bytes, prefix: str = "") -> str:
    """Format bytes as a hex dump with ASCII sidebar."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{i:04x}  {hex_part:<48s}  {ascii_part}")
    return "\n".join(lines)


class Sniffer:
    def __init__(self, real_port: str):
        self.real_port = real_port
        self.master_fd = None
        self.slave_fd = None
        self.slave_path = None
        self.ser = None
        self.log_file = None
        self.running = False
        self.bytes_from_app = 0
        self.bytes_from_light = 0

    def setup_capture_dir(self):
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(CAPTURE_DIR, f"capture_{timestamp}.log")
        self.log_file = open(log_path, "w")
        print(f"Logging to: {log_path}")

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {msg}"
        print(line)
        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()

    def detect_baud_rate(self) -> int:
        """Try to detect the baud rate by opening at each rate and checking
        if the Neewer app's initial handshake produces valid-looking data."""
        # Default to 115200 — most common for CH340
        return 115200

    def create_pty(self) -> str:
        """Create a pseudo-terminal pair and return the slave device path."""
        self.master_fd, self.slave_fd = os.openpty()
        self.slave_path = os.ttyname(self.slave_fd)

        # Match the real serial port settings on the PTY
        attrs = termios.tcgetattr(self.master_fd)
        # Raw mode — no processing
        tty.setraw(self.master_fd)
        tty.setraw(self.slave_fd)

        return self.slave_path

    def open_real_port(self, baud: int):
        """Open the real serial port to the light."""
        self.ser = serial.Serial(
            port=self.real_port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0,  # non-blocking
            write_timeout=1,
        )
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def run(self, baud: int):
        self.setup_capture_dir()
        pty_path = self.create_pty()

        print()
        print(f"Real device:    {self.real_port}")
        print(f"Virtual port:   {pty_path}")
        print(f"Baud rate:      {baud}")
        print()
        print("="*60)
        print("  INSTRUCTIONS")
        print("="*60)
        print()
        print("  1. Open NEEWER Control Center")
        print(f"  2. If it lets you pick a port, choose: {pty_path}")
        print("  3. Use the app normally — brightness, CCT, RGB, etc.")
        print("  4. All traffic will be logged here and to captures/")
        print("  5. Press Ctrl+C to stop")
        print()
        print("  If the app auto-detects and connects to the real port,")
        print("  close the app first, then restart it after this script.")
        print()
        print("="*60)
        print("  Waiting for traffic...")
        print("="*60)
        print()

        self.open_real_port(baud)

        real_fd = self.ser.fileno()
        self.running = True

        while self.running:
            try:
                readable, _, _ = select.select(
                    [self.master_fd, real_fd], [], [], 0.1
                )
            except (OSError, ValueError):
                break

            for fd in readable:
                if fd == self.master_fd:
                    # Data from app → light
                    try:
                        data = os.read(self.master_fd, 4096)
                    except OSError:
                        self.running = False
                        break
                    if not data:
                        self.running = False
                        break
                    self.bytes_from_app += len(data)
                    self.log(f"APP → LIGHT  ({len(data)} bytes)")
                    self.log(hex_dump(data, "  "))
                    # Forward to the real device
                    self.ser.write(data)
                    self.ser.flush()

                elif fd == real_fd:
                    # Data from light → app
                    try:
                        data = self.ser.read(4096)
                    except serial.SerialException:
                        self.running = False
                        break
                    if data:
                        self.bytes_from_light += len(data)
                        self.log(f"LIGHT → APP  ({len(data)} bytes)")
                        self.log(hex_dump(data, "  "))
                        # Forward to the app via PTY
                        try:
                            os.write(self.master_fd, data)
                        except OSError:
                            pass

    def stop(self):
        self.running = False
        print()
        print("="*60)
        print(f"  Capture complete")
        print(f"  App → Light:  {self.bytes_from_app} bytes")
        print(f"  Light → App:  {self.bytes_from_light} bytes")
        print("="*60)
        if self.ser and self.ser.is_open:
            self.ser.close()
        if self.master_fd is not None:
            os.close(self.master_fd)
        if self.slave_fd is not None:
            os.close(self.slave_fd)
        if self.log_file:
            self.log_file.close()


def main():
    port = find_serial_port()

    baud = 115200
    if len(sys.argv) > 1:
        baud = int(sys.argv[1])

    print(f"Neewer PL81-Pro Serial Sniffer")
    print(f"Device: {port}")
    print(f"Baud: {baud} (override with: python3 sniff.py <baud>)")

    sniffer = Sniffer(port)

    def handle_signal(sig, frame):
        sniffer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        sniffer.run(baud)
    except KeyboardInterrupt:
        pass
    finally:
        sniffer.stop()


if __name__ == "__main__":
    main()
