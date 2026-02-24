/// Neewer PL81-Pro USB serial protocol.
///
/// Command format: [0x3A] [tag] [payload_len] [payload...] [cs_hi] [cs_lo]
/// Checksum: 16-bit big-endian sum of all preceding bytes.

pub const TEMP_MIN_K: u32 = 2900;
pub const TEMP_MAX_K: u32 = 7000;
pub const TEMP_STEPS: u32 = 18; // 0x00 = 2900K, 0x12 = 7000K

/// 16-bit big-endian checksum of all bytes.
fn checksum(data: &[u8]) -> [u8; 2] {
    let s: u16 = data.iter().map(|&b| b as u16).sum();
    [(s >> 8) as u8, (s & 0xFF) as u8]
}

/// Build a complete command packet with checksum.
fn build_packet(payload: &[u8]) -> Vec<u8> {
    let cs = checksum(payload);
    let mut pkt = payload.to_vec();
    pkt.extend_from_slice(&cs);
    pkt
}

/// Build a CCT command: brightness 0-100, temperature in Kelvin.
pub fn cct_command(brightness: u8, kelvin: u32) -> Vec<u8> {
    let bri = brightness.min(100);
    let temp = kelvin_to_byte(kelvin);
    build_packet(&[0x3A, 0x02, 0x03, 0x01, bri, temp])
}

/// Convert Kelvin (2900-7000) to protocol byte (0x00-0x12).
pub fn kelvin_to_byte(kelvin: u32) -> u8 {
    let k = kelvin.clamp(TEMP_MIN_K, TEMP_MAX_K);
    let step = ((k - TEMP_MIN_K) as f64 * TEMP_STEPS as f64 / (TEMP_MAX_K - TEMP_MIN_K) as f64)
        .round() as u8;
    step.min(TEMP_STEPS as u8)
}

/// Convert protocol byte (0x00-0x12) to Kelvin.
pub fn byte_to_kelvin(b: u8) -> u32 {
    let b = (b as u32).min(TEMP_STEPS);
    TEMP_MIN_K + (b * (TEMP_MAX_K - TEMP_MIN_K) + TEMP_STEPS / 2) / TEMP_STEPS
}

/// Parse an 8-byte status/echo packet. Returns (brightness, temp_byte) or None.
pub fn parse_status(data: &[u8]) -> Option<(u8, u8)> {
    if data.len() >= 8 && data[0] == 0x3A && data[1] == 0x02 {
        let expected = checksum(&data[..6]);
        if data[6] == expected[0] && data[7] == expected[1] {
            return Some((data[4], data[5]));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_checksum() {
        // 3A 02 03 01 64 09 → sum = 0x00AD
        let cs = checksum(&[0x3A, 0x02, 0x03, 0x01, 0x64, 0x09]);
        assert_eq!(cs, [0x00, 0xAD]);
    }

    #[test]
    fn test_cct_command() {
        let cmd = cct_command(100, 7000);
        // brightness=100=0x64, temp=0x12 for 7000K
        assert_eq!(&cmd[..6], &[0x3A, 0x02, 0x03, 0x01, 0x64, 0x12]);
        assert_eq!(cmd.len(), 8);
    }

    #[test]
    fn test_kelvin_roundtrip() {
        assert_eq!(kelvin_to_byte(2900), 0);
        assert_eq!(kelvin_to_byte(7000), 18);
        assert_eq!(byte_to_kelvin(0), 2900);
        assert_eq!(byte_to_kelvin(18), 7000);
        // midpoint
        assert_eq!(kelvin_to_byte(4950), 9);
    }

    #[test]
    fn test_parse_status() {
        let pkt = cct_command(50, 4950);
        let (bri, temp) = parse_status(&pkt).unwrap();
        assert_eq!(bri, 50);
        assert_eq!(temp, 9);
    }
}
