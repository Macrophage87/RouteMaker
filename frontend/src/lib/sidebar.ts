/**
 * The sidebar redesign's decisions (OWNER-DECISIONS 312, mockup v3), kept out of
 * App.tsx so they are tested without a browser: what the bottom bar offers, what
 * each of its sheets is called, the one-line lede over the points, the tips'
 * toggle words, and "Copy link".
 */
import type { PresetId } from "./presets.ts";

/** The views the panel body shows: the planner, or one of the bottom bar's sheets. */
export type PanelView = "planner" | "layers" | "gpx" | "about";

/** The sheets, and where each one's heading is (the focus goes to it on open). */
export const SHEET_TITLES: Record<Exclude<PanelView, "planner">, string> = {
  layers: "Map layers",
  gpx: "GPX file",
  about: "About RouteMaker",
};

export interface BarItem {
  /** The button's own id, for the focus on the way back. */
  id: "layers" | "legend" | "gpx" | "about";
  /** Its text, always shown beside the icon. */
  label: string;
  /** The sheet it opens. */
  opens: Exclude<PanelView, "planner">;
  /** Whether the sheet opens scrolled to the legend. */
  toLegend?: boolean;
  /** What a screen reader hears besides the label. */
  description: string;
}

/**
 * Map layers, Legend, GPX and About. The mockup's fourth button is Settings,
 * but the app has no settings page: what a settings page would hold lives in
 * the ride settings (the Ride line's Edit) and the Map layers sheet, so the
 * fourth button is the page's one remaining piece, About and sign-in.
 */
export const BAR_ITEMS: readonly BarItem[] = [
  { id: "layers", label: "Map layers", opens: "layers", description: "Opens the map layers and their switches." },
  { id: "legend", label: "Legend", opens: "layers", toLegend: true, description: "Opens the map legend, in the map layers." },
  { id: "gpx", label: "GPX", opens: "gpx", description: "Opens the GPX file tools: open a file, or download the route." },
  { id: "about", label: "About", opens: "about", description: "Opens notes on planning without signing in, and sign in." },
];

export const MORE_TIPS = "More tips";
export const FEWER_TIPS = "Fewer tips";

/** The one line over the points, until there is a start; the full how-to is behind "More tips" (emptyPlanHint). */
export function searchLede(preset: PresetId, loop: boolean): string {
  void preset;
  return loop
    ? "Search, or click the map: start, then stops. The ride comes back to the start."
    : "Search, or click the map: start, then end. Later clicks add stops.";
}

/** The Ride line's action: Edit while closed, Done while open. */
export function rideActionLabel(open: boolean): string {
  return open ? "Done" : "Edit";
}

export const COPY_LINK = "Copy link";
export const COPY_LINK_DONE = "Link copied.";
export const COPY_LINK_FAILED = "Could not copy. Copy the address from the browser's address bar.";

/**
 * What "Copy link" copies: the address as it stands. The plan lives in the
 * fragment (planHash.ts), which carries the points, the ride type and the
 * sliders and never the rider and bike weight (OWNER-DECISIONS 313).
 */
export function linkToCopy(location: { href: string }): string {
  return location.href;
}

/** The surface "Copy link" uses: the async clipboard where there is one, else the selection method. */
export interface ClipboardLike {
  writeText?: (text: string) => Promise<void>;
}

export async function copyText(
  text: string,
  clipboard: ClipboardLike | undefined,
  fallback: (text: string) => boolean,
): Promise<boolean> {
  try {
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the selection method.
  }
  try {
    return fallback(text);
  } catch {
    return false;
  }
}

/** The selection method, in the page (a textarea, execCommand), for a browser with no async clipboard. */
export function selectionCopy(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  const done = document.execCommand("copy");
  area.remove();
  return done;
}

/** A fold's summary text with its count: "Directions (12 steps)", "Junctions to watch (4)". */
export function foldTitle(title: string, count: string | number | null): string {
  return count === null ? title : `${title} (${count})`;
}

export function stepsCount(n: number): string {
  return n === 1 ? "1 step" : `${n} steps`;
}
