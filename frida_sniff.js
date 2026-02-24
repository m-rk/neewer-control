/*
 * Frida script to intercept write() and read() syscalls from the Neewer app.
 * Logs all writes to fd=11 (the serial port) with full buffer hex dumps.
 *
 * Usage:
 *   frida -p <PID> -l frida_sniff.js
 *   Then move sliders in the Neewer app.
 */

// Hook write()
Interceptor.attach(Module.getExportByName(null, "write"), {
    onEnter: function (args) {
        this.fd = args[0].toInt32();
        this.buf = args[1];
        this.count = args[2].toInt32();
    },
    onLeave: function (retval) {
        var fd = this.fd;
        var count = this.count;
        var written = retval.toInt32();

        // Only log writes to fd 11 (serial port) with reasonable sizes
        if (fd === 11 && count > 0 && count <= 256) {
            var data = this.buf.readByteArray(count);
            var hex = Array.from(new Uint8Array(data))
                .map(b => ('0' + b.toString(16)).slice(-2))
                .join(' ');

            // Check if it looks like a serial command (starts with 0x3A)
            var bytes = new Uint8Array(data);
            var marker = "";
            if (bytes.length === 8) {
                var checksum = 0;
                for (var i = 0; i < 7; i++) checksum += bytes[i];
                checksum &= 0xFF;
                if (checksum === bytes[7]) {
                    marker = " [CHECKSUM OK]";
                }
            }

            send("[WRITE] fd=" + fd + " count=" + count + " written=" + written +
                 ": [" + hex + "]" + marker);
        }
    }
});

// Hook read()
Interceptor.attach(Module.getExportByName(null, "read"), {
    onEnter: function (args) {
        this.fd = args[0].toInt32();
        this.buf = args[1];
        this.count = args[2].toInt32();
    },
    onLeave: function (retval) {
        var fd = this.fd;
        var bytesRead = retval.toInt32();

        if (fd === 11 && bytesRead > 0 && bytesRead <= 256) {
            var data = this.buf.readByteArray(bytesRead);
            var hex = Array.from(new Uint8Array(data))
                .map(b => ('0' + b.toString(16)).slice(-2))
                .join(' ');

            send("[READ]  fd=" + fd + " count=" + bytesRead +
                 ": [" + hex + "]");
        }
    }
});

// Also hook ioctl to see modem control
Interceptor.attach(Module.getExportByName(null, "ioctl"), {
    onEnter: function (args) {
        this.fd = args[0].toInt32();
        this.request = args[1].toInt32() >>> 0;  // unsigned
    },
    onLeave: function (retval) {
        // Only log serial-related ioctls on fd 11
        // Skip TIOCMGET (0x4004746a) as it fires too often
        if (this.fd === 11 && this.request !== 0x4004746a) {
            send("[IOCTL] fd=" + this.fd +
                 " cmd=0x" + this.request.toString(16) +
                 " ret=" + retval.toInt32());
        }
    }
});

send("=== Frida hook active. Move sliders in Neewer app! ===");
