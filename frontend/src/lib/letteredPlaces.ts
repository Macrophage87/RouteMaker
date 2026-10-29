/**
 * Lettered places (the owner, 2026-10-11 21:04 UTC): "When offering destinations like water, restrooms,
 * metro, etc, show those locations on the map with letters corresponding to the options. Selecting on the
 * map or pressing the letter both works."
 *
 * The nearest water, restrooms and Metro stations, and the food found, are lettered A, B, C... in their list
 * and on the map, where each is a real button (MapView `lettered`) named "B: Drinking water, Garfield Park,
 * 0.3 mi (0.5 km)": the letter in a pin shape, so neither colour nor shape is needed alone. A tap on the
 * marker or the letter's key (while that list's sheet is open) opens its card (lib/stopCard.ts: what's there, the
 * website, Route here or Add as stop; Stephen 2026-10-19: "don't auto route"); the row's Ride here acts at once.
 */
import type { LonLat } from "./geo.ts";
import { formatDistance } from "./format.ts";

export interface LetteredPlace {
  /** A, B, C...; past Z, AA, AB... (only A to Z have a key). */
  letter: string;
  point: LonLat;
  /** The marker's accessible name: "B: Drinking water, Garfield Park, 0.3 mi (0.5 km)". */
  name: string;
}

/** The letter for the option at `index` (0 is A); past Z it goes on AA, AB, as a spreadsheet's columns do. */
export function placeLetter(index: number): string {
  let n = Math.max(0, Math.floor(index));
  let out = "";
  do {
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}

/** The marker's name: the letter, the place and how far, US units first. */
export function letteredName(letter: string, title: string, metres: number | null): string {
  return metres === null ? `${letter}: ${title}` : `${letter}: ${title}, ${formatDistance(metres)}`;
}

/** The places, lettered in their order. */
export function letterPlaces<T>(items: readonly T[], of: (item: T) => { point: LonLat; title: string; metres: number | null }): LetteredPlace[] {
  return items.map((item, index) => {
    const { point, title, metres } = of(item);
    const letter = placeLetter(index);
    return { letter, point, name: letteredName(letter, title, metres) };
  });
}

/**
 * The option a key press picks: a single letter, A to Z in either case, within the list; null for any other
 * key, with Ctrl, Alt or Meta held, while typing in a field (so a search box keeps its letters), or on the map
 * or in a dialog.
 */
export function letterKeyIndex(
  event: { key: string; ctrlKey?: boolean; altKey?: boolean; metaKey?: boolean; target?: unknown },
  count: number,
): number | null {
  if (event.ctrlKey || event.altKey || event.metaKey) return null;
  const target = event.target as { tagName?: string; isContentEditable?: boolean; closest?: (selector: string) => unknown } | null | undefined;
  const tag = target?.tagName?.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) return null;
  // The map's own keys (I, the arrows) and a dialog's stay theirs; a popup sheet (Sidebar.tsx SheetFrame) is the
  // list's own sheet, a <dialog> since the popups, so its letters still pick.
  if (target?.closest?.(".map, dialog:not(.popup-sheet)")) return null;
  if (!/^[a-zA-Z]$/.test(event.key)) return null;
  const index = event.key.toUpperCase().charCodeAt(0) - 65;
  return index < count ? index : null;
}
