#!/bin/bash
#
# Trace all read/write syscalls from the NEEWER Control Center app.
# Requires: sudo (dtrace needs root)
#
# Usage:
#   1. Open the NEEWER Control Center app and connect to the light
#   2. Run: sudo bash dtrace_sniff.sh
#   3. Use the app (change brightness, CCT, etc.)
#   4. Ctrl+C to stop
#
# Output is hex-dumped bytes with direction (read/write) and timestamps.

set -e

APP_NAME="NEEWER Control"

# Find the PID
PID=$(pgrep -f "$APP_NAME" 2>/dev/null | head -1)

if [ -z "$PID" ]; then
    echo "ERROR: NEEWER Control Center is not running."
    echo "Start the app first, then run this script."
    exit 1
fi

echo "Found NEEWER Control Center PID: $PID"
echo "Tracing read/write syscalls... (Ctrl+C to stop)"
echo "Use the app now — change brightness, CCT, effects, etc."
echo "============================================================"

# dtrace script:
# - Traces write() and read() syscalls for the target PID
# - Dumps the buffer contents as hex
# - Filters to small transfers (< 256 bytes) to avoid noise from UI/network
sudo dtrace -n '
syscall::write:entry
/pid == '"$PID"' && arg2 > 0 && arg2 < 256/
{
    self->buf = arg1;
    self->len = arg2;
    self->fd = arg0;
}

syscall::write:return
/self->buf && self->len > 0/
{
    printf("\n[%Y] WRITE fd=%d len=%d\n", walltimestamp, self->fd, self->len);
    tracemem(copyin(self->buf, self->len), 64);
    self->buf = 0;
    self->len = 0;
}

syscall::read:entry
/pid == '"$PID"'/
{
    self->rbuf = arg1;
    self->rfd = arg0;
}

syscall::read:return
/self->rbuf && arg1 > 0 && arg1 < 256/
{
    printf("\n[%Y] READ  fd=%d len=%d\n", walltimestamp, self->rfd, (int)arg1);
    tracemem(copyin(self->rbuf, arg1), 64);
    self->rbuf = 0;
}
' 2>&1
