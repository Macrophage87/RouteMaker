/**
 * The units the app shows and says (the owner, 2026-11-03: "have a metric mode in settings"). US is the
 * default: miles, feet and mph first, metric in brackets (OWNER-DECISIONS 85). Metric turns that round:
 * kilometres, metres and km/h first, US in brackets, and Ride's voice says metres and kilometres.
 *
 * Settings > Display > Units. Kept in this browser and, signed in, with the account's settings ("units",
 * lib/accountSettings.ts). Changing it reloads the page, as Language does, so every label follows it.
 * Stored values and API fields stay metric whatever the choice.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";

export type Units = "us" | "metric";
export const UNITS: readonly Units[] = ["us", "metric"];
export const UNITS_STORAGE_KEY = "routemaker.units";

/** "us" or "metric", or null for anything else. */
export function unitsOf(value: unknown): Units | null {
  return value === "us" || value === "metric" ? value : null;
}

/** The kept choice, US when none. */
export function readUnits(store: KeyValueStore | null = browserStore()): Units {
  try {
    return unitsOf(store?.getItem(UNITS_STORAGE_KEY) ?? null) ?? "us";
  } catch {
    return "us";
  }
}

/** The kept setting for the account: undefined when never chosen on this device. */
export function unitsSetting(raw: string | null): Units | undefined {
  return unitsOf(raw) ?? undefined;
}

export function writeUnits(units: Units, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(UNITS_STORAGE_KEY, units);
  } catch {
    // Not kept: it holds for this visit.
  }
}

let current: Units = readUnits();

/** The units in use on this page. */
export function units(): Units {
  return current;
}

/** True when metric comes first. */
export function metricFirst(): boolean {
  return current === "metric";
}

export function setUnitsForTest(next: Units): void {
  current = next;
}

/**
 * Keeps the choice and reloads, so every label, chart and spoken cue follows it. `beforeReload` (signed in: the
 * account's save) is waited for, at most four seconds, so the account does not put the old units back on the reload;
 * where it answers false (not saved), or does not answer in time, the old choice is put back and nothing reloads.
 * Where this browser will not keep it, nothing reloads either (a reload would only read the old choice back).
 * True when the page reloads.
 */
export async function chooseUnits(next: Units, beforeReload?: () => Promise<boolean>, store: KeyValueStore | null = browserStore()): Promise<boolean> {
  if (next === current) return false;
  const before = current;
  writeUnits(next, store);
  if (readUnits(store) !== next) return false;
  if (beforeReload) {
    const saved = await Promise.race([beforeReload().catch(() => false), new Promise<boolean>((done) => setTimeout(() => done(false), 4000))]);
    if (!saved) {
      writeUnits(before, store);
      return false;
    }
  }
  current = next;
  if (typeof location !== "undefined") location.reload();
  return true;
}

/**
 * Chosen during a ride (Stephen 2026-11-03: "Change should happen immediately"): no reload, which would stop the cues
 * until Resume and lose the ride's figures. The choice is kept and, signed in, saved to the account first as
 * chooseUnits does; then it is in use at once, and the ride's screen, figured at each render, follows (subscribeUnits).
 * What was figured once at load (the planner's labels, the map's contour labels) follows on the reload owed for the
 * ride's end (unitsReloadOwed; App's Done on the ride summary). True when switched.
 */
export async function switchUnitsInRide(next: Units, beforeSave?: () => Promise<boolean>, store: KeyValueStore | null = browserStore()): Promise<boolean> {
  if (next === current) return false;
  const before = current;
  writeUnits(next, store);
  if (readUnits(store) !== next) return false;
  if (beforeSave) {
    const saved = await Promise.race([beforeSave().catch(() => false), new Promise<boolean>((done) => setTimeout(() => done(false), 4000))]);
    if (!saved) {
      writeUnits(before, store);
      return false;
    }
  }
  current = next;
  reloadOwed = true;
  for (const listener of listeners) listener();
  return true;
}

let reloadOwed = false;
const listeners = new Set<() => void>();

/** Units switched during a ride: the page reloads once the ride is done, so everything figured at load follows. */
export function unitsReloadOwed(): boolean {
  return reloadOwed;
}

/** Called when the units in use change during a ride (useSyncExternalStore with `units`). */
export function subscribeUnits(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
