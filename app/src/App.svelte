<script lang="ts">
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";
  import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { load, type Store } from "@tauri-apps/plugin-store";
  import { register, unregisterAll } from "@tauri-apps/plugin-global-shortcut";

  const TEMP_MIN = 2900;
  const TEMP_MAX = 7000;
  const TEMP_STEP = 205;
  const BRI_GAMMA = 2.0;

  function sliderToHw(slider: number): number {
    return Math.round(Math.pow(slider / 100, BRI_GAMMA) * 100);
  }

  function hwToSlider(hw: number): number {
    return Math.round(Math.pow(hw / 100, 1 / BRI_GAMMA) * 100);
  }

  function kelvinToColor(k: number, alpha = 1): string {
    const t = (k - TEMP_MIN) / (TEMP_MAX - TEMP_MIN);
    const r = Math.round(255 - t * 15);
    const g = Math.round(210 + t * 40);
    const b = Math.round(140 + t * 115);
    return alpha < 1
      ? `rgba(${r}, ${g}, ${b}, ${alpha})`
      : `rgb(${r}, ${g}, ${b})`;
  }

  let brightness = $state(100);
  let kelvin = $state(4950);
  let isOn = $state(true);
  let connected = $state(false);
  let store: Store | null = $state(null);
  let suppressEcho = $state(false);

  interface Preset {
    name: string;
    brightness: number;
    kelvin: number;
  }
  let presets: Preset[] = $state([]);

  let lastOnBrightness = $state(100);

  // Settings panel state
  let showSettings = $state(false);

  interface ShortcutConfig {
    modifiers: string[];
    toggleKey: string;
    presetKeys: string[];
  }
  let shortcutConfig: ShortcutConfig = $state({
    modifiers: ["CommandOrControl", "Alt", "Shift"],
    toggleKey: "`",
    presetKeys: ["1", "2", "3", "4"],
  });
  let listeningFor: string | null = $state(null);

  const MODIFIER_OPTIONS = [
    { id: "CommandOrControl", label: "\u2318 Cmd" },
    { id: "Shift", label: "\u21E7 Shift" },
    { id: "Alt", label: "\u2325 Opt" },
    { id: "Control", label: "\u2303 Ctrl" },
  ];

  function buildShortcutString(key: string): string {
    return [...shortcutConfig.modifiers, key].join("+");
  }

  function eventToTauriKey(e: KeyboardEvent): string | null {
    const code = e.code;
    if (code.startsWith("Digit")) return code.slice(5);
    if (code.startsWith("Key")) return code.slice(3).toUpperCase();
    const map: Record<string, string> = {
      Backquote: "`", Minus: "-", Equal: "=",
      BracketLeft: "[", BracketRight: "]", Backslash: "\\",
      Semicolon: ";", Quote: "'", Comma: ",", Period: ".", Slash: "/",
      Space: "Space", Enter: "Enter", Tab: "Tab",
      ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right",
      Escape: "Escape", Backspace: "Backspace", Delete: "Delete",
      Home: "Home", End: "End", PageUp: "PageUp", PageDown: "PageDown",
    };
    for (let i = 1; i <= 12; i++) map[`F${i}`] = `F${i}`;
    return map[code] ?? null;
  }

  function displayKey(tauriKey: string): string {
    const map: Record<string, string> = {
      "`": "`", Space: "Space", Up: "\u2191", Down: "\u2193", Left: "\u2190", Right: "\u2192",
      Escape: "Esc", Backspace: "\u232B", Delete: "Del",
    };
    return map[tauriKey] ?? tauriKey;
  }

  async function registerShortcuts() {
    try {
      await unregisterAll();
    } catch {}
    if (shortcutConfig.modifiers.length === 0) return;

    try {
      await register(buildShortcutString(shortcutConfig.toggleKey), (e) => {
        if (e.state === "Pressed") togglePower();
      });
    } catch (e) {
      console.error("Failed to register toggle shortcut:", e);
    }

    for (let i = 0; i < presets.length; i++) {
      const key = shortcutConfig.presetKeys[i];
      if (!key) continue;
      const presetIndex = i;
      try {
        await register(buildShortcutString(key), (e) => {
          if (e.state === "Pressed") applyPreset(presets[presetIndex]);
        });
      } catch (e) {
        console.error(`Failed to register preset ${i} shortcut:`, e);
      }
    }
  }

  async function saveShortcutConfig() {
    await saveState();
    await registerShortcuts();
  }

  function toggleModifier(mod: string) {
    if (shortcutConfig.modifiers.includes(mod)) {
      shortcutConfig.modifiers = shortcutConfig.modifiers.filter((m) => m !== mod);
    } else {
      shortcutConfig.modifiers = [...shortcutConfig.modifiers, mod];
    }
    saveShortcutConfig();
  }

  function handleKeyCapture(e: KeyboardEvent, target: string) {
    e.preventDefault();
    e.stopPropagation();
    const ignoredCodes = ["ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight"];
    if (ignoredCodes.includes(e.code)) return;
    const key = eventToTauriKey(e);
    if (!key) return;
    if (target === "toggle") {
      shortcutConfig.toggleKey = key;
    } else if (target.startsWith("preset-")) {
      const idx = parseInt(target.slice(7));
      shortcutConfig.presetKeys[idx] = key;
      shortcutConfig.presetKeys = [...shortcutConfig.presetKeys];
    }
    listeningFor = null;
    saveShortcutConfig();
  }

  let previewColor = $derived(kelvinToColor(kelvin));
  let hwBrightness = $derived(sliderToHw(brightness) / 100);
  let previewOpacity = $derived(0.4 + hwBrightness * 0.6);
  let glowSpread = $derived(Math.round(20 + hwBrightness * 60));
  let glowOpacity = $derived(hwBrightness * 0.8);

  async function sendLight() {
    if (!connected) return;
    const bri = isOn ? sliderToHw(brightness) : 0;
    suppressEcho = true;
    try {
      await invoke("set_light", { brightness: bri, kelvin });
    } catch (e) {
      console.error("set_light failed:", e);
    }
    setTimeout(() => (suppressEcho = false), 600);
    await saveState();
  }

  async function saveState() {
    if (!store) return;
    await store.set("brightness", brightness);
    await store.set("kelvin", kelvin);
    await store.set("isOn", isOn);
    await store.set("presets", presets);
    await store.set("shortcutConfig", shortcutConfig);
  }

  async function loadState() {
    store = await load("settings.json", { autoSave: false });
    brightness = ((await store.get("brightness")) as number) ?? 100;
    kelvin = ((await store.get("kelvin")) as number) ?? 4950;
    isOn = ((await store.get("isOn")) as boolean) ?? true;
    presets = ((await store.get("presets")) as Preset[]) ?? [];
    const savedShortcuts = (await store.get("shortcutConfig")) as ShortcutConfig | null;
    if (savedShortcuts) shortcutConfig = savedShortcuts;
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

  function applyPreset(p: Preset) {
    brightness = p.brightness;
    kelvin = p.kelvin;
    isOn = true;
    sendLight();
  }

  function saveCurrentAsPreset() {
    if (presets.length >= 4) return;
    const defaultKeys = ["1", "2", "3", "4"];
    if (shortcutConfig.presetKeys.length < presets.length + 1) {
      shortcutConfig.presetKeys = [...shortcutConfig.presetKeys, defaultKeys[presets.length] ?? String(presets.length + 1)];
    }
    presets = [
      ...presets,
      { name: `Preset ${presets.length + 1}`, brightness, kelvin },
    ];
    saveShortcutConfig();
  }

  function deletePreset(index: number) {
    presets = presets.filter((_, i) => i !== index);
    shortcutConfig.presetKeys.splice(index, 1);
    shortcutConfig.presetKeys = [...shortcutConfig.presetKeys];
    saveShortcutConfig();
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

  let sendTimer: ReturnType<typeof setTimeout> | null = null;
  function throttledSend() {
    if (sendTimer) clearTimeout(sendTimer);
    sendTimer = setTimeout(() => sendLight(), 30);
  }

  function handleSliderInput() {
    if (!isOn) {
      isOn = true;
    }
    throttledSend();
  }

  onMount(async () => {
    await loadState();
    await registerShortcuts();
    await checkConnection();

    if (connected) sendLight();

    await listen<{ brightness: number; kelvin: number }>(
      "light-status",
      (event) => {
        if (suppressEcho) return;
        brightness = hwToSlider(event.payload.brightness);
        kelvin = event.payload.kelvin;
        isOn = event.payload.brightness > 0;
        if (brightness > 0) lastOnBrightness = brightness;
        saveState();
      }
    );

    await listen("serial-disconnected", () => {
      connected = false;
      const interval = setInterval(async () => {
        await checkConnection();
        if (connected) {
          clearInterval(interval);
          sendLight();
        }
      }, 2000);
    });

    const appWindow = getCurrentWebviewWindow();
    appWindow.onFocusChanged(({ payload: focused }) => {
      if (!focused) {
        listeningFor = null;
        appWindow.hide();
      }
    });

    setInterval(checkConnection, 5000);
  });
</script>

<div class="panel" role="application">
  <div class="flip-container" class:flipped={showSettings}>
    <div class="flip-front">
      <div class="main-area">
        <!-- Brightness slider (left) -->
        <div class="slider-col">
          <!-- Lucide: sun (filled center) -->
          <svg class="slider-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="4" fill="currentColor"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
          </svg>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            bind:value={brightness}
            oninput={handleSliderInput}
            class="vslider brightness-slider"
            orient="vertical"
          />
          <!-- Lucide: sun-medium (shorter rays = dimmer) -->
          <svg class="slider-icon dim" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="4"/><path d="M12 3v1"/><path d="M12 20v1"/><path d="M3 12h1"/><path d="M20 12h1"/><path d="m18.364 5.636-.707.707"/><path d="m6.343 17.657-.707.707"/><path d="m5.636 5.636.707.707"/><path d="m17.657 17.657.707.707"/>
          </svg>
        </div>

        <!-- Center: preview + power + presets -->
        <div class="center-col">
          <div class="top-bar">
            <div class="connection-dot" class:online={connected} title="{connected ? 'Connected' : 'Disconnected'}"></div>
            <button class="settings-btn" aria-label="Settings" onclick={() => showSettings = true}>
              <!-- Lucide: settings -->
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
                <circle cx="12" cy="12" r="3"/>
              </svg>
            </button>
          </div>
          <div
            class="preview"
            class:off={!isOn}
            onclick={togglePower}
            role="button"
            tabindex="0"
            onkeydown={(e: KeyboardEvent) => e.key === "Enter" && togglePower()}
            style="box-shadow: 0 0 {isOn ? glowSpread : 0}px {Math.round((isOn ? glowSpread : 0) / 3)}px {kelvinToColor(kelvin, isOn ? glowOpacity : 0)}; cursor: pointer;"
          >
            <div
              class="preview-core"
              style="background: radial-gradient(ellipse at center, #fff 0%, {previewColor} 40%, transparent 70%); opacity: {isOn ? previewOpacity : 0};"
            ></div>
            <div
              class="preview-bloom"
              style="background: radial-gradient(ellipse at center, {previewColor} 0%, transparent 60%); opacity: {isOn ? glowOpacity : 0};"
            ></div>
            <div
              class="preview-edge"
              style="box-shadow: inset 0 0 {glowSpread}px {previewColor}; opacity: {isOn ? glowOpacity : 0};"
            ></div>
            <div
              class="power-icon"
              class:on={isOn}
              class:disconnected={!connected}
              class:hidden={showSettings}
              style="box-shadow: 0 0 {isOn ? Math.round(10 + hwBrightness * 20) : 0}px {kelvinToColor(kelvin, isOn ? 0.3 + hwBrightness * 0.4 : 0)};"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="{isOn ? `filter: drop-shadow(0 0 4px currentColor);` : ''}">
                <path d="M12 3v8"/>
                <path d="M18.36 6.64A9 9 0 1 1 5.64 6.64"/>
              </svg>
            </div>
          </div>

          <div class="presets-row">
            {#each presets as preset, i}
              <div
                class="preset-swatch"
                onclick={() => applyPreset(preset)}
                onkeydown={(e: KeyboardEvent) => e.key === "Enter" && applyPreset(preset)}
                role="button"
                tabindex="0"
                title="{preset.brightness}% · {preset.kelvin}K"
                style="box-shadow: 0 0 {Math.round(4 + (sliderToHw(preset.brightness) / 100) * 8)}px {kelvinToColor(preset.kelvin, (sliderToHw(preset.brightness) / 100) * 0.5)};"
              >
                <div
                  class="swatch-core"
                  style="background: radial-gradient(ellipse at center, #fff 0%, {kelvinToColor(preset.kelvin)} 50%, transparent 80%); opacity: {0.4 + (sliderToHw(preset.brightness) / 100) * 0.6};"
                ></div>
                <div
                  class="swatch-glow"
                  style="box-shadow: inset 0 0 {Math.round(8 + (sliderToHw(preset.brightness) / 100) * 20)}px {kelvinToColor(preset.kelvin)}; opacity: {(sliderToHw(preset.brightness) / 100) * 0.8};"
                ></div>
                <button
                  class="swatch-delete"
                  onclick={(e: MouseEvent) => { e.stopPropagation(); deletePreset(i); }}
                  aria-label="Delete preset"
                >&times;</button>
              </div>
            {/each}
            {#if presets.length < 4}
              <button class="preset-add" onclick={saveCurrentAsPreset} aria-label="Save preset">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M12 5v14M5 12h14"/>
                </svg>
              </button>
            {/if}
          </div>
        </div>

        <!-- Temperature slider (right) -->
        <div class="slider-col">
          <!-- Lucide: snowflake -->
          <svg class="slider-icon cool" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m10 20-1.25-2.5L6 18"/><path d="M10 4 8.75 6.5 6 6"/><path d="m14 20 1.25-2.5L18 18"/><path d="m14 4 1.25 2.5L18 6"/><path d="m17 21-3-6h-4"/><path d="m17 3-3 6 1.5 3"/><path d="M2 12h6.5L10 9"/><path d="m20 10-1.5 2 1.5 2"/><path d="M22 12h-6.5L14 15"/><path d="m4 10 1.5 2L4 14"/><path d="m7 21 3-6-1.5-3"/><path d="m7 3 3 6h4"/>
          </svg>
          <input
            type="range"
            min={TEMP_MIN}
            max={TEMP_MAX}
            step={TEMP_STEP}
            bind:value={kelvin}
            oninput={handleSliderInput}
            class="vslider temp-slider"
            orient="vertical"
          />
          <!-- Lucide: flame -->
          <svg class="slider-icon warm" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4"/>
          </svg>
        </div>
      </div>
    </div>

    <div class="flip-back">
      <div class="settings-view">
        <div class="settings-header">
          <button class="back-btn" onclick={() => { showSettings = false; listeningFor = null; }} aria-label="Back">
            <!-- Lucide: chevron-left -->
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m15 18-6-6 6-6"/>
            </svg>
          </button>
          <span class="settings-title">Settings</span>
        </div>

        <div class="settings-section">
          <div class="setting-label">Global shortcuts</div>
          <div class="modifier-row">
            {#each MODIFIER_OPTIONS as mod}
              <button
                class="modifier-pill"
                class:active={shortcutConfig.modifiers.includes(mod.id)}
                onclick={() => toggleModifier(mod.id)}
              >{mod.label}</button>
            {/each}
          </div>
        </div>

        <div class="settings-section">
          <div class="shortcut-row">
            <span class="shortcut-label">Light On/Off</span>
            <button
              class="key-capture-btn"
              class:listening={listeningFor === 'toggle'}
              onclick={() => listeningFor = listeningFor === 'toggle' ? null : 'toggle'}
              onkeydown={(e: KeyboardEvent) => listeningFor === 'toggle' && handleKeyCapture(e, 'toggle')}
            >{listeningFor === 'toggle' ? '...' : displayKey(shortcutConfig.toggleKey)}</button>
          </div>

          <div class="shortcut-hint">Keys 1–4 activate presets when held with modifiers above</div>
        </div>

        <div class="settings-footer">
          <button class="quit-btn" onclick={() => getCurrentWindow().destroy()}>Quit App</button>
        </div>
      </div>
    </div>
  </div>
</div>

<style>
  :global(html),
  :global(body) {
    margin: 0;
    padding: 0;
    background: transparent;
    border-radius: 12px;
    overflow: hidden;
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
    border-radius: 12px;
    perspective: 800px;
    overflow: hidden;
    width: 320px;
    height: 340px;
  }

  .flip-container {
    position: relative;
    width: 100%;
    height: 100%;
    transform-style: preserve-3d;
    transition: transform 0.5s;
  }

  .flip-container.flipped {
    transform: rotateY(180deg);
  }

  .flip-front,
  .flip-back {
    position: absolute;
    inset: 0;
    backface-visibility: hidden;
    -webkit-backface-visibility: hidden;
    padding: 16px;
    padding-top: 24px;
    display: flex;
    flex-direction: column;
  }

  .flip-back {
    transform: rotateY(180deg);
  }

  /* Layout */
  .main-area {
    display: flex;
    gap: 12px;
    align-items: stretch;
    flex: 1;
  }

  .slider-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
    width: 32px;
  }

  .center-col {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
  }

  .top-bar {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: -6px;
    padding: 0 2px;
  }

  .connection-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #555;
    transition: background 0.3s;
  }

  .connection-dot.online {
    background: #34c759;
    box-shadow: 0 0 6px rgba(52, 199, 89, 0.5);
  }

  .settings-btn {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    border: none;
    background: none;
    color: rgba(255, 255, 255, 0.35);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    transition: color 0.2s;
  }

  .settings-btn:hover {
    color: rgba(255, 255, 255, 0.7);
  }

  /* Slider icons */
  .slider-icon {
    color: rgba(255, 255, 255, 0.6);
    flex-shrink: 0;
  }

  .slider-icon.dim {
    color: rgba(255, 255, 255, 0.5);
  }

  .slider-icon.cool {
    color: #a8c4ff;
  }

  .slider-icon.warm {
    color: #ff9329;
  }

  /* Vertical sliders */
  .vslider {
    -webkit-appearance: slider-vertical;
    appearance: slider-vertical;
    writing-mode: vertical-lr;
    direction: rtl;
    width: 8px;
    flex: 1;
    min-height: 0;
    border-radius: 4px;
    outline: none;
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
  }

  .brightness-slider {
    background: linear-gradient(to top, #222, #fff);
  }

  .temp-slider {
    background: linear-gradient(to top, #ff9329, #fff, #a8c4ff);
  }

  .vslider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #fff;
    border: 2px solid rgba(0, 0, 0, 0.3);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
    cursor: pointer;
    transition: box-shadow 0.15s;
  }

  .vslider::-webkit-slider-thumb:hover {
    box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.15), 0 1px 4px rgba(0, 0, 0, 0.4);
  }

  .vslider::-webkit-slider-thumb:active {
    box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.2), 0 1px 4px rgba(0, 0, 0, 0.4);
  }

  /* Preview */
  .preview {
    width: 100%;
    aspect-ratio: 1;
    border-radius: 10px;
    overflow: hidden;
    position: relative;
    background: rgba(255, 255, 255, 0.03);
    transition: background 0.3s, box-shadow 0.3s;
  }

  .preview.off {
    background: rgba(255, 255, 255, 0.02);
  }

  .preview-core {
    position: absolute;
    inset: -20%;
    transition: opacity 0.3s;
  }

  .preview-bloom {
    position: absolute;
    inset: -50%;
    transition: opacity 0.3s;
  }

  .preview-edge {
    position: absolute;
    inset: 0;
    border-radius: 10px;
    transition: opacity 0.3s;
  }

  /* Power icon (centered in preview) */
  .power-icon {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 1px solid transparent;
    background: rgba(30, 30, 30, 0.95);
    color: rgba(255, 255, 255, 0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.3s;
    z-index: 1;
  }

  .power-icon.on {
    color: rgba(255, 255, 255, 0.9);
    border-color: rgba(255, 255, 255, 0.2);
  }

  .power-icon.disconnected {
    color: #ff453a;
    border-color: rgba(255, 69, 58, 0.3);
  }

  .power-icon.hidden {
    display: none;
  }

  .preview:hover .power-icon.on {
    border-color: rgba(255, 255, 255, 0.3);
  }

  .preview:hover .power-icon:not(.on) {
    box-shadow: 0 0 16px rgba(255, 255, 255, 0.3) !important;
  }

  /* Presets row */
  .presets-row {
    display: flex;
    gap: 6px;
    justify-content: center;
    align-items: center;
    min-height: 38px;
  }

  .preset-swatch {
    width: 36px;
    height: 36px;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(0, 0, 0, 0.3);
    cursor: pointer;
    position: relative;
    overflow: hidden;
    padding: 0;
    transition: border-color 0.15s;
  }

  .preset-swatch:hover {
    border-color: rgba(255, 255, 255, 0.3);
  }

  .swatch-core {
    position: absolute;
    inset: -40%;
    transition: opacity 0.15s;
  }

  .swatch-glow {
    position: absolute;
    inset: 0;
    border-radius: 5px;
    transition: opacity 0.15s;
  }

  .swatch-delete {
    position: absolute;
    top: -1px;
    right: 0px;
    width: 16px;
    height: 16px;
    border-radius: 0 5px 0 4px;
    border: none;
    background: rgba(0, 0, 0, 0.7);
    color: rgba(255, 255, 255, 0.7);
    font-size: 11px;
    line-height: 1;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.15s;
    padding: 0;
    z-index: 1;
  }

  .preset-swatch:hover .swatch-delete {
    opacity: 1;
  }

  .swatch-delete:hover {
    background: rgba(255, 69, 58, 0.8);
    color: #fff;
  }

  .preset-add {
    width: 36px;
    height: 36px;
    border-radius: 6px;
    border: 1px dashed rgba(255, 255, 255, 0.15);
    background: none;
    color: rgba(255, 255, 255, 0.3);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    padding: 0;
  }

  .preset-add:hover {
    border-color: rgba(255, 255, 255, 0.3);
    color: rgba(255, 255, 255, 0.6);
    background: rgba(255, 255, 255, 0.05);
  }

  /* Settings view */
  .settings-view {
    display: flex;
    flex-direction: column;
    gap: 14px;
    height: 100%;
  }

  .settings-header {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .back-btn {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    border: none;
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    transition: background 0.15s;
  }

  .back-btn:hover {
    background: rgba(255, 255, 255, 0.15);
  }

  .settings-title {
    font-size: 13px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
  }

  .settings-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .setting-label {
    font-size: 11px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.45);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .modifier-row {
    display: flex;
    gap: 6px;
  }

  .modifier-pill {
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.05);
    color: rgba(255, 255, 255, 0.5);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .modifier-pill:hover {
    border-color: rgba(255, 255, 255, 0.25);
    color: rgba(255, 255, 255, 0.7);
  }

  .modifier-pill.active {
    background: rgba(59, 130, 246, 0.25);
    border-color: rgba(59, 130, 246, 0.5);
    color: rgba(255, 255, 255, 0.9);
  }

  .shortcut-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 0;
  }

  .shortcut-label {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
  }

  .key-capture-btn {
    min-width: 40px;
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.8);
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    text-align: center;
    transition: all 0.15s;
  }

  .key-capture-btn:hover {
    border-color: rgba(255, 255, 255, 0.3);
    background: rgba(255, 255, 255, 0.1);
  }

  .key-capture-btn.listening {
    border-color: rgba(59, 130, 246, 0.7);
    background: rgba(59, 130, 246, 0.15);
    animation: pulse-border 1s ease-in-out infinite;
  }

  @keyframes pulse-border {
    0%, 100% { border-color: rgba(59, 130, 246, 0.4); }
    50% { border-color: rgba(59, 130, 246, 0.9); }
  }

  .shortcut-hint {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.35);
    line-height: 1.4;
  }

  .settings-footer {
    margin-top: auto;
  }

  .quit-btn {
    width: 100%;
    padding: 7px 0;
    border-radius: 6px;
    border: 1px solid rgba(255, 69, 58, 0.3);
    background: rgba(255, 69, 58, 0.1);
    color: #ff453a;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    transition: all 0.15s;
  }

  .quit-btn:hover {
    background: rgba(255, 69, 58, 0.2);
    border-color: rgba(255, 69, 58, 0.5);
  }
</style>
