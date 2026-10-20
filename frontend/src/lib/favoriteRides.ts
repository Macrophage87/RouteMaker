/**
 * Favorite ride types (Stephen, 2026-10-19: "Allow users to select favorite ride types that appear
 * first when selecting ride mode").
 *
 * A star on each ride type's card, in Go's More ride types and in Plan's ride type dialog, marks it a
 * favorite; the favorites are listed first, under their own heading, in the order they were starred.
 * Nothing is added to Go's main screen. Kept on this device (localStorage) and, signed in, in the
 * account's saved settings (lib/accountSettings.ts "favorites"), so they follow the rider.
 *
 * One small store with listeners, so the two pickers and the settings sync see the same list without
 * passing it through the app.
 */
import { createElement as h, useSyncExternalStore, type ReactElement } from "react";
import { ICON_PATHS } from "./iconPaths.ts";
import { presetSaid, resolvePreset, type PresetId } from "./presets.ts";

export const FAVORITES_KEY = "routemaker.favorite-rides";

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function local(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The ride types a stored or answered list names, each once, in order; anything else is left out. */
export function parseFavorites(raw: unknown): PresetId[] {
  if (!Array.isArray(raw)) return [];
  const out: PresetId[] = [];
  for (const value of raw) {
    const id = resolvePreset(value);
    if (id && !out.includes(id)) out.push(id);
  }
  return out;
}

/** This device's favorites. */
export function readFavorites(store: Store | null = local()): PresetId[] {
  try {
    const raw = store?.getItem(FAVORITES_KEY);
    return raw ? parseFavorites(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

/** The list with a ride type starred (added last) or unstarred. */
export function toggled(favorites: readonly PresetId[], id: PresetId): PresetId[] {
  return favorites.includes(id) ? favorites.filter((f) => f !== id) : [...favorites, id];
}

let current: PresetId[] | null = null;
const listeners = new Set<() => void>();

function snapshot(): PresetId[] {
  if (current === null) current = readFavorites();
  return current;
}

/** Keep a new list on this device and tell every picker. */
export function setFavorites(favorites: readonly PresetId[], store: Store | null = local()): void {
  current = parseFavorites(favorites);
  try {
    store?.setItem(FAVORITES_KEY, JSON.stringify(current));
  } catch {
    // Not kept: it still applies to this visit.
  }
  for (const listener of listeners) listener();
}

/** Star or unstar one ride type. */
export function toggleFavorite(id: PresetId): void {
  setFavorites(toggled(snapshot(), id));
}

/** Read the device's list again (after the account's settings are put on the device). */
export function reloadFavorites(): void {
  current = readFavorites();
  for (const listener of listeners) listener();
}

// A star pressed in another tab reaches this one's pickers (and so its next settings save).
const onStorage = (event: StorageEvent) => {
  if (event.key === FAVORITES_KEY) reloadFavorites();
};

export const subscribe = (listener: () => void) => {
  if (listeners.size === 0 && typeof window !== "undefined") window.addEventListener("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
};

const EMPTY: PresetId[] = [];

/** The favorites, kept current. */
export function useFavoriteRides(): PresetId[] {
  return useSyncExternalStore(subscribe, snapshot, () => EMPTY);
}

/** The star's spoken name: "Favorite Cargo Bike"; pressed when it is one. */
export function favoriteLabel(id: PresetId): string {
  return `Favorite ${presetSaid(id)}`;
}

/** What a picker's DOM offers the refocus: enough for a test to stand in for it. */
interface Scope {
  querySelector(selector: string): { focus(): void; closest(selector: string): { open: boolean } | null } | null;
}

/**
 * Star or unstar a ride type from a picker. The card moves (into Favorites or back to its group), so
 * the focus follows its star to where it now is in `scope`, rather than being lost. The star's own
 * name and pressed state say the change; nothing else is announced, so it is heard once.
 */
export function toggleFromPicker(id: PresetId, scope: Scope | null, frame: (run: () => void) => void = defaultFrame): void {
  toggleFavorite(id);
  frame(() => {
    const star = scope?.querySelector(`.ride-fav[data-fav="${id}"]`);
    // Back in a folded group (Go's More ride types): open it, so the star can take the focus.
    const fold = star?.closest("details");
    if (fold && !fold.open) fold.open = true;
    star?.focus();
  });
}

function defaultFrame(run: () => void): void {
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
}

/**
 * The star: a toggle button beside a ride type's card. Its name is the ride type's ("Favorite Cargo
 * Bike") and its pressed state says whether it is one. A createElement component, so a test renders it.
 */
export function FavoriteStar({ id, on, onToggle }: { id: PresetId; on: boolean; onToggle: (id: PresetId) => void }): ReactElement {
  return h(
    "button",
    {
      type: "button",
      className: "ride-fav",
      "data-fav": id,
      "aria-pressed": on,
      "aria-label": favoriteLabel(id),
      onClick: () => onToggle(id),
    },
    h("svg", {
      className: "icon",
      width: 22,
      height: 22,
      viewBox: "0 0 24 24",
      fill: on ? "currentColor" : "none",
      stroke: "currentColor",
      strokeWidth: 2,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      "aria-hidden": "true",
      focusable: "false",
      dangerouslySetInnerHTML: { __html: ICON_PATHS.star },
    }),
  );
}
