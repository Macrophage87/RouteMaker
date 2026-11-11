/**
 * How the map draws a note's or a stop's icon (Stephen 2026-11-10: "Allow both", "We can use noto"): Google's Noto
 * Emoji pictures, bundled with the app so a sign looks the same on every phone (our default), or the phone's own emoji.
 * Kept on this device, as Settings > Display's other choices are. The pictures themselves are app/iconArt.tsx's.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import { t } from "./i18n.ts";

export type IconStyle = "noto" | "emoji";

export const ICON_STYLE_KEY = "routemaker.iconStyle";
/** Sent on the window when the choice changes, so the signs already on the map are drawn again. */
export const ICON_STYLE_EVENT = "routemaker:iconstyle";
export const ICON_STYLE_LABEL = t("Phone emoji on map signs");
export const ICON_STYLE_HELP = t("Notes and stops on the map show your phone's own emoji, not the app's pictures. Kept on this device.");

// The choice made on this visit, for when the device keeps nothing.
let thisVisit: IconStyle | null = null;

export function readIconStyle(store: KeyValueStore | null = browserStore()): IconStyle {
  if (thisVisit) return thisVisit;
  try {
    return store?.getItem(ICON_STYLE_KEY) === "emoji" ? "emoji" : "noto";
  } catch {
    return "noto";
  }
}

export function writeIconStyle(style: IconStyle, store: KeyValueStore | null = browserStore()): void {
  thisVisit = style;
  try {
    store?.setItem(ICON_STYLE_KEY, style);
  } catch {
    // Blocked site data: the choice holds for this visit only.
  }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(ICON_STYLE_EVENT));
}
