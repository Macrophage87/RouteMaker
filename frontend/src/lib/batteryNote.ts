/**
 * The battery-saver line at the first Start ride in the Android app (backlog 2026-11-12, "Ready for a dozen testers";
 * the owner, 2026-11-12: one line at the first Start ride, only when the phone's battery optimisation would stop
 * RouteMaker). Some makers' battery savers stop foreground services, so cues go silent mid-ride (mobile/README.md,
 * battery). The app's RouteMakerBattery plugin (mobile/android/.../BatteryPlugin.java) says whether RouteMaker is
 * battery-optimised and whether the phone's maker is one known to stop rides; both, and the line shows once.
 * A browser, or an app built before the plugin, shows nothing.
 */
import { nativeBridge, type CapacitorBridge } from "./nativeShell.ts";
import { t } from "./i18n.ts";

export const BATTERY_PLUGIN = "RouteMakerBattery";
/** Set once the rider has closed the line or pressed its button (our default: once per install). */
export const BATTERY_SHOWN_KEY = "routemaker.batteryNoteShown";

export const BATTERY_LINE = () => t("Your phone may stop RouteMaker during a ride.");
export const BATTERY_FIX = () => t("Set battery to Unrestricted");

export interface Shown {
  get(): boolean;
  set(): void;
}

export const shownOnThisDevice: Shown = {
  get() {
    try {
      return window.localStorage.getItem(BATTERY_SHOWN_KEY) === "1";
    } catch {
      return false;
    }
  },
  set() {
    try {
      window.localStorage.setItem(BATTERY_SHOWN_KEY, "1");
    } catch {
      // Private storage off: the line may show again, which is harmless.
    }
  },
};

function hasPlugin(bridge: CapacitorBridge): boolean {
  try {
    return typeof bridge.isPluginAvailable === "function" && bridge.isPluginAvailable(BATTERY_PLUGIN) === true;
  } catch {
    return false;
  }
}

/**
 * Whether to show the line now: the app, the plugin, not dismissed before, optimised, a strict maker. It is marked
 * seen only when the rider closes it or presses its button (markBatteryNoteSeen), so a line drawn while the ride's
 * notes were folded away comes back at the next Start ride.
 */
export async function batteryNoteDue(bridge: CapacitorBridge | null = nativeBridge(), shown: Shown = shownOnThisDevice): Promise<boolean> {
  if (!bridge || !hasPlugin(bridge) || shown.get()) return false;
  try {
    const answer = (await bridge.nativePromise(BATTERY_PLUGIN, "check", {})) as { optimised?: unknown; strictMaker?: unknown } | null;
    return answer?.optimised === true && answer.strictMaker === true;
  } catch {
    return false;
  }
}

export function markBatteryNoteSeen(shown: Shown = shownOnThisDevice): void {
  shown.set();
}

export async function openBatterySettings(bridge: CapacitorBridge | null = nativeBridge()): Promise<boolean> {
  if (!bridge) return false;
  try {
    await bridge.nativePromise(BATTERY_PLUGIN, "openSettings", {});
    return true;
  } catch {
    return false;
  }
}
