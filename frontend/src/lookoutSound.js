// Browser-only audio. IDs are retained across Alerts page mounts in this tab.
export const seenLookoutIds = new Set();
export const SOUND_KEY = "watchlistLookoutSound";

export function savedSoundPreference() {
  try {
    return localStorage.getItem(SOUND_KEY) === "on";
  } catch {
    return false;
  }
}

export function saveSoundPreference(enabled) {
  try {
    localStorage.setItem(SOUND_KEY, enabled ? "on" : "off");
  } catch {
    /* visual alerts still work */
  }
}

export async function unlockAudio(current) {
  const Constructor = window.AudioContext || window.webkitAudioContext;
  if (!Constructor) throw new Error("Audio unavailable");
  const context = current || new Constructor();
  try {
    await context.resume();
  } catch (failure) {
    if (!current) await context.close().catch(() => {});
    throw failure;
  }
  return context;
}

export function notificationTone(context) {
  if (!context || context.state !== "running") return false;
  try {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const at = context.currentTime;
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(660, at);
    oscillator.frequency.setValueAtTime(880, at + 0.12);
    gain.gain.setValueAtTime(0, at);
    gain.gain.linearRampToValueAtTime(0.13, at + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.001, at + 0.34);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.onended = () => {
      oscillator.disconnect();
      gain.disconnect();
    };
    oscillator.start(at);
    oscillator.stop(at + 0.36);
    return true;
  } catch {
    return false;
  }
}
