#include <IOKit/hid/IOHIDManager.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Neewer PL81-Pro USB HID Probe v4
 * Protocol decoded from NEEWER Control Center binary disassembly.
 *
 * USB Command format: [0x3A] [tag] [payload_len] [payload...] [cs_hi] [cs_lo]
 * Checksum: 16-bit big-endian sum of all preceding bytes
 * Sending: prepend 1-byte data length, reportID = original data length
 */

static FILE *g_log = NULL;

static void out(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    vfprintf(stdout, fmt, ap);
    fflush(g_log);
    va_end(ap);
}

static void hex_dump(const uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; i++)
        out("%02x ", data[i]);
}

static void usb_checksum(const uint8_t *data, size_t len, uint8_t *cs_hi, uint8_t *cs_lo) {
    uint16_t sum = 0;
    for (size_t i = 0; i < len; i++) sum += data[i];
    *cs_hi = (sum >> 8) & 0xFF;
    *cs_lo = sum & 0xFF;
}

static int send_hid(IOHIDDeviceRef dev, const uint8_t *cmd, size_t cmd_len,
                    int report_type, CFIndex report_id, int pad_to,
                    const char *label) {
    uint8_t report[192];
    memset(report, 0, sizeof(report));
    size_t send_len = cmd_len;
    if (pad_to > 0) send_len = (size_t)pad_to;
    if (send_len > sizeof(report)) send_len = sizeof(report);
    memcpy(report, cmd, cmd_len < send_len ? cmd_len : send_len);

    IOReturn ret = IOHIDDeviceSetReport(dev, report_type, report_id, report, send_len);

    out("  %-48s type=%d id=%-4ld len=%-4zu [", label, report_type, (long)report_id, send_len);
    hex_dump(cmd, cmd_len);
    out("] -> 0x%08x %s\n", ret, ret == kIOReturnSuccess ? "SUCCESS!" : "");
    return ret == kIOReturnSuccess;
}

int main(void) {
    const char *logpath = "/Users/mark/Code/m-rk/neewer-control/hid_probe_output.txt";
    g_log = fopen(logpath, "w");
    if (!g_log) { perror("fopen"); return 1; }

    out("=== Neewer PL81-Pro HID Probe v4 ===\n");
    out("Protocol from binary disassembly\n\n");

    IOHIDManagerRef mgr = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
    IOHIDManagerSetDeviceMatching(mgr, NULL);
    IOReturn ret = IOHIDManagerOpen(mgr, kIOHIDOptionsTypeNone);
    out("HID Manager open: 0x%08x\n", ret);
    if (ret != kIOReturnSuccess) {
        out("FAILED — need Input Monitoring permission.\n");
        fclose(g_log);
        return 1;
    }

    CFSetRef devices = IOHIDManagerCopyDevices(mgr);
    CFIndex count = CFSetGetCount(devices);
    const void **devs = malloc(count * sizeof(void *));
    CFSetGetValues(devices, devs);
    out("HID devices found: %ld\n\n", (long)count);

    IOHIDDeviceRef target = NULL;
    for (CFIndex i = 0; i < count; i++) {
        IOHIDDeviceRef d = (IOHIDDeviceRef)devs[i];
        CFNumberRef vidRef = IOHIDDeviceGetProperty(d, CFSTR(kIOHIDVendorIDKey));
        CFNumberRef pidRef = IOHIDDeviceGetProperty(d, CFSTR(kIOHIDProductIDKey));
        if (!vidRef || !pidRef) continue;
        int32_t vid = 0, pid = 0;
        CFNumberGetValue(vidRef, kCFNumberSInt32Type, &vid);
        CFNumberGetValue(pidRef, kCFNumberSInt32Type, &pid);
        if (vid == 0x0BDA && pid == 0x1100) {
            out("Found: Realtek HID VID=0x%04x PID=0x%04x\n", vid, pid);
            ret = IOHIDDeviceOpen(d, kIOHIDOptionsTypeNone);
            out("  Open: 0x%08x\n\n", ret);
            if (ret == kIOReturnSuccess) { target = d; break; }
        }
    }

    if (!target) {
        out("No Realtek HID device found or failed to open.\n");
        free(devs); fclose(g_log); return 1;
    }

    int any_ok = 0;
    uint8_t cs_hi, cs_lo;

    /* === Build USB commands (decoded from binary) === */

    /* Power ON: 3A 06 01 01 + 16-bit checksum */
    uint8_t pwr_on_raw[] = {0x3A, 0x06, 0x01, 0x01};
    usb_checksum(pwr_on_raw, 4, &cs_hi, &cs_lo);
    uint8_t pwr_on[] = {0x3A, 0x06, 0x01, 0x01, cs_hi, cs_lo};

    /* Power OFF: 3A 06 01 02 + 16-bit checksum */
    uint8_t pwr_off_raw[] = {0x3A, 0x06, 0x01, 0x02};
    usb_checksum(pwr_off_raw, 4, &cs_hi, &cs_lo);
    uint8_t pwr_off[] = {0x3A, 0x06, 0x01, 0x02, cs_hi, cs_lo};

    /* CCT 100% 7000K: 3A 02 03 01 64 09 + 16-bit checksum */
    uint8_t cct100_raw[] = {0x3A, 0x02, 0x03, 0x01, 0x64, 0x09};
    usb_checksum(cct100_raw, 6, &cs_hi, &cs_lo);
    uint8_t cct100[] = {0x3A, 0x02, 0x03, 0x01, 0x64, 0x09, cs_hi, cs_lo};

    /* CCT 10% 7000K: 3A 02 03 01 0A 09 + 16-bit checksum */
    uint8_t cct10_raw[] = {0x3A, 0x02, 0x03, 0x01, 0x0A, 0x09};
    usb_checksum(cct10_raw, 6, &cs_hi, &cs_lo);
    uint8_t cct10[] = {0x3A, 0x02, 0x03, 0x01, 0x0A, 0x09, cs_hi, cs_lo};

    /* ================================================================ */
    /* ROUND 1: Exact app protocol (length prefix + reportID=dataLen)   */
    /* ================================================================ */
    out("--- Round 1: Exact app protocol (len prefix, reportID=dataLen, pad=192) ---\n");
    {
        /* Power ON */
        uint8_t r1[192]; memset(r1, 0, sizeof(r1));
        r1[0] = sizeof(pwr_on);  /* length prefix byte */
        memcpy(r1 + 1, pwr_on, sizeof(pwr_on));
        any_ok |= send_hid(target, r1, 1 + sizeof(pwr_on),
                           kIOHIDReportTypeOutput, sizeof(pwr_on), 192, "Power ON");
        sleep(1);

        /* CCT 100% */
        uint8_t r2[192]; memset(r2, 0, sizeof(r2));
        r2[0] = sizeof(cct100);
        memcpy(r2 + 1, cct100, sizeof(cct100));
        any_ok |= send_hid(target, r2, 1 + sizeof(cct100),
                           kIOHIDReportTypeOutput, sizeof(cct100), 192, "CCT 100% 7000K");
        sleep(1);

        /* CCT 10% */
        uint8_t r3[192]; memset(r3, 0, sizeof(r3));
        r3[0] = sizeof(cct10);
        memcpy(r3 + 1, cct10, sizeof(cct10));
        any_ok |= send_hid(target, r3, 1 + sizeof(cct10),
                           kIOHIDReportTypeOutput, sizeof(cct10), 192, "CCT 10% 7000K");
        sleep(1);

        /* Power OFF */
        uint8_t r4[192]; memset(r4, 0, sizeof(r4));
        r4[0] = sizeof(pwr_off);
        memcpy(r4 + 1, pwr_off, sizeof(pwr_off));
        any_ok |= send_hid(target, r4, 1 + sizeof(pwr_off),
                           kIOHIDReportTypeOutput, sizeof(pwr_off), 192, "Power OFF");
    }
    out("\n");

    /* ================================================================ */
    /* ROUND 2: No length prefix, reportID=0, pad=192                   */
    /* ================================================================ */
    out("--- Round 2: No len prefix, reportID=0, pad=192 ---\n");
    any_ok |= send_hid(target, pwr_on, sizeof(pwr_on),
                       kIOHIDReportTypeOutput, 0, 192, "Power ON");
    any_ok |= send_hid(target, cct100, sizeof(cct100),
                       kIOHIDReportTypeOutput, 0, 192, "CCT 100% 7000K");
    out("\n");

    /* ================================================================ */
    /* ROUND 3: Exact length (no padding)                                */
    /* ================================================================ */
    out("--- Round 3: No padding, various reportIDs ---\n");
    any_ok |= send_hid(target, pwr_on, sizeof(pwr_on),
                       kIOHIDReportTypeOutput, sizeof(pwr_on), 0, "PwrON rid=dataLen nopad");
    any_ok |= send_hid(target, pwr_on, sizeof(pwr_on),
                       kIOHIDReportTypeOutput, 0, 0, "PwrON rid=0 nopad");
    {
        uint8_t r[7]; r[0] = sizeof(pwr_on); memcpy(r+1, pwr_on, sizeof(pwr_on));
        any_ok |= send_hid(target, r, sizeof(r),
                           kIOHIDReportTypeOutput, sizeof(pwr_on), 0, "PwrON lenprefix rid=dataLen nopad");
    }
    out("\n");

    /* ================================================================ */
    /* ROUND 4: kIOHIDReportTypeInput (0) — some devices need this      */
    /* ================================================================ */
    out("--- Round 4: Report type = Input (0) ---\n");
    {
        uint8_t r[192]; memset(r, 0, sizeof(r));
        r[0] = sizeof(pwr_on); memcpy(r+1, pwr_on, sizeof(pwr_on));
        any_ok |= send_hid(target, r, 1+sizeof(pwr_on),
                           kIOHIDReportTypeInput, sizeof(pwr_on), 192, "PwrON Input type");
    }
    {
        uint8_t r[192]; memset(r, 0, sizeof(r));
        r[0] = sizeof(cct100); memcpy(r+1, cct100, sizeof(cct100));
        any_ok |= send_hid(target, r, 1+sizeof(cct100),
                           kIOHIDReportTypeInput, sizeof(cct100), 192, "CCT100 Input type");
    }
    out("\n");

    /* ================================================================ */
    /* ROUND 5: kIOHIDReportTypeFeature (2)                              */
    /* ================================================================ */
    out("--- Round 5: Report type = Feature (2) ---\n");
    {
        uint8_t r[192]; memset(r, 0, sizeof(r));
        r[0] = sizeof(pwr_on); memcpy(r+1, pwr_on, sizeof(pwr_on));
        any_ok |= send_hid(target, r, 1+sizeof(pwr_on),
                           kIOHIDReportTypeFeature, sizeof(pwr_on), 192, "PwrON Feature type");
    }
    out("\n");

    /* ================================================================ */
    /* ROUND 6: Try seizing the device first                             */
    /* ================================================================ */
    out("--- Round 6: Seize device then send ---\n");
    IOHIDDeviceClose(target, kIOHIDOptionsTypeNone);
    ret = IOHIDDeviceOpen(target, kIOHIDOptionsTypeSeizeDevice);
    out("  Re-open with Seize: 0x%08x\n", ret);
    if (ret == kIOReturnSuccess) {
        uint8_t r[192]; memset(r, 0, sizeof(r));
        r[0] = sizeof(cct100); memcpy(r+1, cct100, sizeof(cct100));
        any_ok |= send_hid(target, r, 1+sizeof(cct100),
                           kIOHIDReportTypeOutput, sizeof(cct100), 192,
                           "CCT100 seized Output");
        any_ok |= send_hid(target, cct100, sizeof(cct100),
                           kIOHIDReportTypeOutput, 0, 192,
                           "CCT100 seized noprefix rid=0");
    }
    out("\n");

    if (any_ok) {
        out("*** SUCCESS! At least one command worked! ***\n");
    } else {
        out("All commands failed.\n");
        out("If all return 0xe0005000, this is a USB pipe stall.\n");
        out("The device may need the com.apple.security.device.usb entitlement\n");
        out("signed by a proper Developer ID certificate.\n");
    }

    IOHIDDeviceClose(target, kIOHIDOptionsTypeNone);
    free(devs);
    CFRelease(devices);
    IOHIDManagerClose(mgr, kIOHIDOptionsTypeNone);

    out("\nDone.\n");
    fclose(g_log);
    return 0;
}
