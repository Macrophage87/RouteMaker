/**
 * Go's map layers (follow-up review of PR #95; owner decision pending, this is the recommended default): Go opens
 * with the water and restroom layer and the Metro and MARC stations off, so the phone's map shows the route and
 * little else (the owner's Go rule, 2026-10-11: "Ideally you should just want to find a destination and go").
 * Plan keeps today's defaults (all on). A rider's own Layers choice is kept on this device and wins in both
 * views. The Water and Restroom chips still letter their places while their sheet is open (those markers are not
 * the layer).
 *
 * Pure apart from the stores, so the order is tested without a browser.
 */
import type { AppMode } from "./appMode.ts";
import type { RailVisibility } from "./railStations.ts";
import { WATER_PREFS_DEFAULT, type WaterPrefs } from "./waterRestrooms.ts";

/** The rider's Metro and MARC switches, kept on this device once changed. */
export const RAIL_PREFS_KEY = "routemaker.railLayer";

/** Whether a view opens with these layers on when the rider has not chosen: Plan yes, Go no. */
export function layersOnByDefault(mode: AppMode): boolean {
  return mode !== "go";
}

/** The water and restroom switches shown: the rider's own, else the view's default (the sub-switches as before). */
export function waterPrefsFor(chosen: WaterPrefs | null, mode: AppMode): WaterPrefs {
  return chosen ?? { ...WATER_PREFS_DEFAULT, on: layersOnByDefault(mode) };
}

/** The Metro and MARC switches shown: the rider's own, else the view's default. */
export function railFor(chosen: RailVisibility | null, mode: AppMode): RailVisibility {
  if (chosen) return chosen;
  const on = layersOnByDefault(mode);
  return { metro: on, marc: on };
}

type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The rider's kept Metro and MARC switches; null when never changed (or not readable). */
export function readRailChoice(store: Store | null = defaultStore()): RailVisibility | null {
  try {
    const raw = store?.getItem(RAIL_PREFS_KEY);
    if (!raw) return null;
    const kept = JSON.parse(raw) as Partial<Record<keyof RailVisibility, unknown>> | null;
    if (typeof kept?.metro !== "boolean" || typeof kept?.marc !== "boolean") return null;
    return { metro: kept.metro, marc: kept.marc };
  } catch {
    return null;
  }
}

/** Keep the rider's Metro and MARC switches; whether they were kept (not kept, they still hold for this page). */
export function saveRailChoice(choice: RailVisibility, store: Store | null = defaultStore()): boolean {
  try {
    if (!store) return false;
    store.setItem(RAIL_PREFS_KEY, JSON.stringify(choice));
    return true;
  } catch {
    return false;
  }
}
