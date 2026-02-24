/// Tauri commands exposed to the frontend.
use tauri::State;

use crate::protocol;
use crate::serial::SerialManager;

#[tauri::command]
pub fn list_ports() -> Vec<String> {
    serialport::available_ports()
        .unwrap_or_default()
        .into_iter()
        .filter(|p| p.port_name.contains("usbserial"))
        .map(|p| p.port_name)
        .collect()
}

#[tauri::command]
pub fn connect(path: String, app: tauri::AppHandle, state: State<'_, SerialManager>) -> Result<(), String> {
    state.connect(&path, app)
}

#[tauri::command]
pub fn disconnect(state: State<'_, SerialManager>) {
    state.disconnect();
}

#[tauri::command]
pub fn is_connected(state: State<'_, SerialManager>) -> bool {
    state.is_connected()
}

#[tauri::command]
pub fn set_light(brightness: u8, kelvin: u32, state: State<'_, SerialManager>) -> Result<(), String> {
    let cmd = protocol::cct_command(brightness, kelvin);
    state.write(&cmd)
}
