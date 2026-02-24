#!/usr/bin/env python3
"""
Generate an lldb script that captures serial write() calls from the Neewer app.

Usage:
  1. Open the NEEWER Control Center app and connect to the light
  2. Find the PID: ps aux | grep -i neewer
  3. Run: lldb -p <PID> -s lldb_commands.txt
  4. In the app, move sliders/change settings
  5. The script logs all write() calls with buffer contents

This works on macOS with SIP enabled (unlike dtrace) because lldb can attach
to non-system processes.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LLDB_COMMANDS = os.path.join(SCRIPT_DIR, "lldb_commands.txt")

# lldb Python script that logs write() syscall arguments
LLDB_PYTHON_SCRIPT = os.path.join(SCRIPT_DIR, "lldb_write_hook.py")

LLDB_PYTHON_CONTENT = r'''
import lldb

write_count = 0

def write_breakpoint_callback(frame, bp_loc, dict):
    """Called when write() is hit. Logs fd, buf, count."""
    global write_count

    # Get arguments: write(int fd, const void *buf, size_t count)
    # arm64 calling convention: x0=fd, x1=buf, x2=count
    fd = frame.FindRegister("x0").GetValueAsUnsigned()
    buf_ptr = frame.FindRegister("x1").GetValueAsUnsigned()
    count = frame.FindRegister("x2").GetValueAsUnsigned()

    # Only log writes to the serial port fd (typically small: 3-20)
    # and with count == 8 (matching our expected command size)
    if count == 0 or count > 256 or fd > 100:
        return False  # Don't stop

    process = frame.GetThread().GetProcess()
    error = lldb.SBError()
    data = process.ReadMemory(buf_ptr, count, error)

    if error.Success() and data:
        hex_str = " ".join(f"{b:02x}" for b in data)
        write_count += 1
        print(f"[{write_count:4d}] write(fd={fd}, count={count}): [{hex_str}]")

        # Highlight 8-byte writes that start with 0x3A
        if count == 8 and data[0] == 0x3A:
            cs_calc = sum(data[:7]) & 0xFF
            cs_match = "MATCH" if cs_calc == data[7] else "MISMATCH"
            print(f"       ^^^ Serial command! Checksum: calc=0x{cs_calc:02x} actual=0x{data[7]:02x} {cs_match}")

    return False  # Don't stop, just log


def read_breakpoint_callback(frame, bp_loc, dict):
    """Called when read() returns. We break at entry, then check."""
    global write_count

    fd = frame.FindRegister("x0").GetValueAsUnsigned()
    buf_ptr = frame.FindRegister("x1").GetValueAsUnsigned()
    count = frame.FindRegister("x2").GetValueAsUnsigned()

    if count == 0 or count > 256 or fd > 100:
        return False

    # Note: at entry, buffer isn't filled yet. We'd need to break at return.
    # For simplicity, just log that a read was attempted.
    # The actual data capture happens from write() calls.

    return False
'''

LLDB_COMMANDS_CONTENT = f'''
# Load the Python hook script
command script import {LLDB_PYTHON_SCRIPT}

# Set breakpoint on write() and attach our callback
breakpoint set -n write -C "script lldb_write_hook.write_breakpoint_callback(frame, bp_loc, internal_dict)" --auto-continue

# Also try to catch ioctl for serial port ops
# breakpoint set -n ioctl --auto-continue

# Continue execution
process continue
'''


def find_neewer_pid():
    """Find the PID of the running Neewer Control Center app."""
    import subprocess
    result = subprocess.run(
        ["pgrep", "-f", "NEEWER Control Center"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split("\n")
    pids = [p for p in pids if p]
    if not pids:
        return None
    return pids[0]


def main():
    print("Neewer PL81-Pro lldb Serial Sniffer")
    print()

    # Write the Python hook script
    with open(LLDB_PYTHON_SCRIPT, "w") as f:
        f.write(LLDB_PYTHON_CONTENT)
    print(f"Written: {LLDB_PYTHON_SCRIPT}")

    # Write the lldb commands
    with open(LLDB_COMMANDS, "w") as f:
        f.write(LLDB_COMMANDS_CONTENT)
    print(f"Written: {LLDB_COMMANDS}")

    pid = find_neewer_pid()
    if pid:
        print(f"\nNeewer app PID: {pid}")
        print(f"\nRun this command:")
        print(f"  lldb -p {pid} -s {LLDB_COMMANDS}")
    else:
        print("\nNeewer Control Center app not running.")
        print("Start the app first, then run:")
        print(f"  PID=$(pgrep -f 'NEEWER Control Center')")
        print(f"  lldb -p $PID -s {LLDB_COMMANDS}")

    print()
    print("Once lldb is attached and running, move sliders in the app.")
    print("All write() calls will be logged with hex dumps.")
    print("Press Ctrl+C in the lldb terminal to stop.")


if __name__ == "__main__":
    main()
