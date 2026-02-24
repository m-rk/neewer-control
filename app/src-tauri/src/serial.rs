/// Serial port management for Neewer PL81-Pro.
///
/// Handles port discovery, connection, read loop, and write commands.
/// Emits "light-status" events to the frontend when status packets arrive.
use std::io::Read;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter};

use crate::protocol;

#[derive(Debug, Clone, Serialize)]
pub struct LightStatus {
    pub brightness: u8,
    pub kelvin: u32,
}

pub struct SerialManager {
    port: Mutex<Option<Box<dyn serialport::SerialPort>>>,
    reading: Arc<AtomicBool>,
}

impl SerialManager {
    pub fn new() -> Self {
        Self {
            port: Mutex::new(None),
            reading: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Find the first matching USB serial port.
    pub fn find_port() -> Option<String> {
        serialport::available_ports()
            .ok()?
            .into_iter()
            .find(|p| p.port_name.contains("usbserial"))
            .map(|p| p.port_name)
    }

    /// Open the serial port and start the read loop.
    pub fn connect(&self, path: &str, app: AppHandle) -> Result<(), String> {
        // Stop any existing read loop
        self.reading.store(false, Ordering::Relaxed);

        let port = serialport::new(path, 115200)
            .data_bits(serialport::DataBits::Eight)
            .parity(serialport::Parity::None)
            .stop_bits(serialport::StopBits::One)
            .timeout(Duration::from_millis(100))
            .open()
            .map_err(|e| format!("Failed to open {path}: {e}"))?;

        // Clone the port for the read thread
        let reader = port
            .try_clone()
            .map_err(|e| format!("Failed to clone port: {e}"))?;

        *self.port.lock().unwrap() = Some(port);

        // Start background read loop
        let reading = self.reading.clone();
        reading.store(true, Ordering::Relaxed);

        std::thread::spawn(move || {
            read_loop(reader, reading, app);
        });

        Ok(())
    }

    /// Send raw bytes to the light.
    pub fn write(&self, data: &[u8]) -> Result<(), String> {
        let mut lock = self.port.lock().unwrap();
        let port = lock.as_mut().ok_or("Port not open")?;
        port.write_all(data).map_err(|e| format!("Write failed: {e}"))?;
        port.flush().map_err(|e| format!("Flush failed: {e}"))?;
        Ok(())
    }

    /// Check if the port is currently open.
    pub fn is_connected(&self) -> bool {
        self.port.lock().unwrap().is_some()
    }

    /// Disconnect and stop the read loop.
    pub fn disconnect(&self) {
        self.reading.store(false, Ordering::Relaxed);
        *self.port.lock().unwrap() = None;
    }
}

/// Background read loop — parses 8-byte status packets and emits events.
fn read_loop(
    mut port: Box<dyn serialport::SerialPort>,
    running: Arc<AtomicBool>,
    app: AppHandle,
) {
    let mut buf = [0u8; 256];
    let mut accum: Vec<u8> = Vec::new();

    while running.load(Ordering::Relaxed) {
        match port.read(&mut buf) {
            Ok(n) if n > 0 => {
                accum.extend_from_slice(&buf[..n]);
                // Try to parse complete 8-byte packets
                while accum.len() >= 8 {
                    // Find 0x3A start byte
                    if let Some(start) = accum.iter().position(|&b| b == 0x3A) {
                        if start > 0 {
                            accum.drain(..start);
                        }
                        if accum.len() < 8 {
                            break;
                        }
                        if let Some((bri, temp_byte)) = protocol::parse_status(&accum[..8]) {
                            let status = LightStatus {
                                brightness: bri,
                                kelvin: protocol::byte_to_kelvin(temp_byte),
                            };
                            let _ = app.emit("light-status", &status);
                        }
                        accum.drain(..8);
                    } else {
                        accum.clear();
                        break;
                    }
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut => continue,
            Err(_) => {
                let _ = app.emit("serial-disconnected", ());
                break;
            }
            _ => continue,
        }
    }
}
