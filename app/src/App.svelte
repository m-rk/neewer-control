<script lang="ts">
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";
  import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
  import { load, type Store } from "@tauri-apps/plugin-store";

  const TEMP_MIN = 2900;
  const TEMP_MAX = 7000;
  const TEMP_STEP = 205; // divides evenly into 4100 (20 steps)
  const BRI_STEP = 5;

  let brightness = $state(100);
  let kelvin = $state(4950);
  let isOn = $state(true);
  let connected = $state(false);
  let store: Store | null = $state(null);
  let suppressEcho = $state(false);

  // Preset type
  interface Preset {
    name: string;
    brightness: number;
    kelvin: number;
  }
  let presets: Preset[] = $state([]);

  // Editing state
  let editingIndex: number | null = $state(null);
  let editName = $state("");

  // Track "last on" brightness for toggle
  let lastOnBrightness = $state(100);

  async function sendLight() {
    if (!connected) return;
    const bri = isOn ? brightness : 0;
    suppressEcho = true;
    try {
      await invoke("set_light", { brightness: bri, kelvin });
    } catch (e) {
      console.error("set_light failed:", e);
    }
    // Clear echo suppression after a short window
    setTimeout(() => (suppressEcho = false), 600);
    await saveState();
  }

  async function saveState() {
    if (!store) return;
    await store.set("brightness", brightness);
    await store.set("kelvin", kelvin);
    await store.set("isOn", isOn);
    await store.set("presets", presets);
  }

  async function loadState() {
    store = await load("settings.json", { autoSave: false });
    brightness = ((await store.get("brightness")) as number) ?? 100;
    kelvin = ((await store.get("kelvin")) as number) ?? 4950;
    isOn = ((await store.get("isOn")) as boolean) ?? true;
    presets = ((await store.get("presets")) as Preset[]) ?? [];
    lastOnBrightness = brightness > 0 ? brightness : 100;
  }

  function togglePower() {
    if (isOn) {
      lastOnBrightness = brightness > 0 ? brightness : lastOnBrightness;
      isOn = false;
    } else {
      isOn = true;
      brightness = lastOnBrightness;
    }
    sendLight();
  }

  function changeBrightness(delta: number) {
    brightness = Math.max(0, Math.min(100, brightness + delta));
    if (!isOn && brightness > 0) isOn = true;
    sendLight();
  }

  function changeTemp(delta: number) {
    kelvin = Math.max(TEMP_MIN, Math.min(TEMP_MAX, kelvin + delta));
    sendLight();
  }

  function applyPreset(p: Preset) {
    brightness = p.brightness;
    kelvin = p.kelvin;
    isOn = true;
    sendLight();
  }

  function saveCurrentAsPreset() {
    if (presets.length >= 5) return;
    presets = [
      ...presets,
      { name: `Preset ${presets.length + 1}`, brightness, kelvin },
    ];
    saveState();
  }

  function updatePreset(index: number) {
    presets[index] = { ...presets[index], brightness, kelvin };
    presets = [...presets];
    saveState();
  }

  function deletePreset(index: number) {
    presets = presets.filter((_, i) => i !== index);
    editingIndex = null;
    saveState();
  }

  function startEditing(index: number) {
    editingIndex = index;
    editName = presets[index].name;
  }

  function finishEditing() {
    if (editingIndex !== null && editName.trim()) {
      presets[editingIndex] = { ...presets[editingIndex], name: editName.trim() };
      presets = [...presets]; // trigger reactivity
      saveState();
    }
    editingIndex = null;
  }

  async function quitApp() {
    await invoke("quit_app");
  }

  async function checkConnection() {
    try {
      connected = await invoke("is_connected");
      if (!connected) {
        const ports: string[] = await invoke("list_ports");
        if (ports.length > 0) {
          await invoke("connect", { path: ports[0] });
          connected = true;
        }
      }
    } catch {
      connected = false;
    }
  }

  // Throttle slider sends
  let sendTimer: ReturnType<typeof setTimeout> | null = null;
  function throttledSend() {
    if (sendTimer) clearTimeout(sendTimer);
    sendTimer = setTimeout(() => sendLight(), 30);
  }

  onMount(async () => {
    await loadState();
    await checkConnection();

    // Send initial state to light
    if (connected) sendLight();

    // Listen for status packets from physical knob
    await listen<{ brightness: number; kelvin: number }>(
      "light-status",
      (event) => {
        if (suppressEcho) return;
        brightness = event.payload.brightness;
        kelvin = event.payload.kelvin;
        isOn = brightness > 0;
        if (brightness > 0) lastOnBrightness = brightness;
        saveState();
      }
    );

    // Listen for disconnection
    await listen("serial-disconnected", () => {
      connected = false;
      // Try to reconnect periodically
      const interval = setInterval(async () => {
        await checkConnection();
        if (connected) {
          clearInterval(interval);
          sendLight();
        }
      }, 2000);
    });

    // Hide panel when it loses focus
    const appWindow = getCurrentWebviewWindow();
    appWindow.onFocusChanged(({ payload: focused }) => {
      if (!focused) appWindow.hide();
    });

    // Periodically check connection (handles USB plug/unplug)
    setInterval(checkConnection, 5000);
  });
</script>

<div class="panel" role="application">
  <!-- Header -->
  <div class="header">
    <span class="title">NeewerControl</span>
    <span class="status" class:online={connected}>
      {connected ? "Connected" : "Disconnected"}
    </span>
  </div>

  <!-- Power toggle -->
  <div class="row">
    <span class="label">Power</span>
    <button class="power-btn" class:on={isOn} onclick={togglePower}>
      {isOn ? "ON" : "OFF"}
    </button>
  </div>

  <!-- Brightness -->
  <div class="control">
    <div class="control-header">
      <span class="label">Brightness</span>
      <span class="value">{isOn ? brightness : 0}%</span>
    </div>
    <input
      type="range"
      min="0"
      max="100"
      step="1"
      bind:value={brightness}
      oninput={throttledSend}
      disabled={!isOn}
      class="slider brightness-slider"
    />
  </div>

  <!-- Temperature -->
  <div class="control">
    <div class="control-header">
      <span class="label">Temperature</span>
      <span class="value">{kelvin}K</span>
    </div>
    <input
      type="range"
      min={TEMP_MIN}
      max={TEMP_MAX}
      step={TEMP_STEP}
      bind:value={kelvin}
      oninput={throttledSend}
      disabled={!isOn}
      class="slider temp-slider"
    />
    <div class="temp-labels">
      <span>Warm</span>
      <span>Cool</span>
    </div>
  </div>

  <!-- Presets -->
  <div class="presets-section">
    <div class="presets-header">
      <span class="label">Presets</span>
      {#if presets.length < 5}
        <button class="save-btn" onclick={saveCurrentAsPreset}>+ Save current</button>
      {/if}
    </div>
    <div class="presets-grid">
      {#each presets as preset, i}
        <div class="preset-item">
          {#if editingIndex === i}
            <input
              class="preset-name-input"
              type="text"
              bind:value={editName}
              onkeydown={(e: KeyboardEvent) => e.key === "Enter" && finishEditing()}
              onblur={finishEditing}
            />
          {:else}
            <button class="preset-btn" onclick={() => applyPreset(preset)} ondblclick={() => startEditing(i)}>
              <span class="preset-name">{preset.name}</span>
              <span class="preset-detail">{preset.brightness}% &middot; {preset.kelvin}K</span>
            </button>
            <div class="preset-actions">
              <button class="icon-btn" onclick={() => updatePreset(i)} title="Update to current values">&#8631;</button>
              <button class="icon-btn" onclick={() => deletePreset(i)} title="Delete">&times;</button>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    <button class="footer-btn" disabled title="Settings">&#9881;</button>
    <button class="footer-btn quit-btn" onclick={quitApp}>Quit</button>
  </div>
</div>

<style>
  :global(html),
  :global(body) {
    margin: 0;
    padding: 0;
    background: transparent;
  }

  :global(body) {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
    font-size: 13px;
    color: #e0e0e0;
    -webkit-user-select: none;
    user-select: none;
  }

  .panel {
    background: rgba(30, 30, 30, 0.95);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 16px;
    padding-top: 24px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .panel::before {
    content: "";
    position: absolute;
    top: -6px;
    left: 50%;
    transform: translateX(-50%);
    width: 12px;
    height: 6px;
    background: rgba(30, 30, 30, 0.95);
    clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .title {
    font-weight: 600;
    font-size: 14px;
    color: #fff;
  }

  .status {
    font-size: 11px;
    color: #888;
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .status::before {
    content: "";
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #666;
  }

  .status.online::before {
    background: #34c759;
  }

  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .label {
    font-weight: 500;
    color: #ccc;
  }

  .power-btn {
    padding: 4px 16px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.05);
    color: #999;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }

  .power-btn.on {
    background: rgba(52, 199, 89, 0.2);
    border-color: rgba(52, 199, 89, 0.4);
    color: #34c759;
  }

  .power-btn:hover {
    background: rgba(255, 255, 255, 0.1);
  }

  .control {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .control-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .value {
    font-variant-numeric: tabular-nums;
    color: #fff;
    font-weight: 500;
  }

  .slider {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 8px;
    border-radius: 4px;
    outline: none;
    cursor: pointer;
  }

  .brightness-slider {
    background: linear-gradient(to right, #333, #fff);
  }

  .temp-slider {
    background: linear-gradient(to right, #ff9329, #fff, #a8c4ff);
  }

  .slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: #fff;
    border: 2px solid rgba(0, 0, 0, 0.4);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
    cursor: pointer;
    transition: box-shadow 0.15s;
  }

  .slider::-webkit-slider-thumb:hover {
    box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.15), 0 1px 4px rgba(0, 0, 0, 0.4);
  }

  .slider::-webkit-slider-thumb:active {
    box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.2), 0 1px 4px rgba(0, 0, 0, 0.4);
  }

  .slider:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .slider:disabled::-webkit-slider-thumb {
    cursor: not-allowed;
  }

  .temp-labels {
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: #666;
    margin-top: -2px;
  }

  .presets-section {
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    padding-top: 12px;
  }

  .presets-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .save-btn {
    font-size: 11px;
    color: #0a84ff;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
  }

  .save-btn:hover {
    text-decoration: underline;
  }

  .presets-grid {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .preset-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .preset-btn {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.05);
    color: #ddd;
    font-size: 12px;
    cursor: pointer;
    text-align: left;
    transition: background 0.15s;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .preset-btn:hover {
    background: rgba(255, 255, 255, 0.1);
  }

  .preset-name {
    line-height: 1.3;
  }

  .preset-detail {
    font-size: 10px;
    color: #777;
    line-height: 1.2;
  }

  .preset-actions {
    display: flex;
    gap: 2px;
  }

  .icon-btn {
    background: none;
    border: none;
    color: #666;
    cursor: pointer;
    font-size: 14px;
    padding: 2px 4px;
    line-height: 1;
  }

  .icon-btn:hover {
    color: #ccc;
  }

  .preset-name-input {
    flex: 1;
    padding: 5px 8px;
    border: 1px solid rgba(10, 132, 255, 0.5);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.08);
    color: #fff;
    font-size: 12px;
    outline: none;
  }

  .footer {
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    padding-top: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .footer-btn {
    background: none;
    border: none;
    color: #777;
    cursor: pointer;
    font-size: 12px;
    padding: 2px 4px;
  }

  .footer-btn:disabled {
    color: #444;
    cursor: default;
  }

  .footer-btn:not(:disabled):hover {
    color: #ccc;
  }

  .quit-btn {
    color: #999;
  }

  .quit-btn:hover {
    color: #ff453a;
  }
</style>
