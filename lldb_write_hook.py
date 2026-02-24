
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
