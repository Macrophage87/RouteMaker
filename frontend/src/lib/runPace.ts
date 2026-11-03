/**
 * Run's pace (Stephen, 2026-11-02, the Run ride type: "a pace setting, about 5 to 7 mph"): one picker in Run's ride
 * settings, a mile pace from 15:00 to 6:00 (4 to 10 mph), 10:00 (6 mph) unless the runner picks another. Sent as the
 * API's `run_pace_kmh` (core/run_plan.py), which times the run and sets Valhalla's walking pace; the grade model still
 * slows the climbs.
 *
 * Kept on this device, as Avoid stairs is (lib/avoidStairs.ts), never in a plan link: the reader's page plans the run
 * again at their own pace. Changing it plans the run shown again (App.tsx, RUN_PACE_EVENT).
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import { KMH_PER_MPH } from "./format.ts";
import { t } from "./i18n.ts";
import { metricFirst } from "./units.ts";

export const RUN_PACE_KEY = "routemaker.run.paceMph";
/** The picker's paces, in mph: a 15:00 mile to a 6:00 one, half a mph apart. */
export const RUN_PACE_MIN_MPH = 4;
export const RUN_PACE_MAX_MPH = 10;
export const RUN_PACE_STEP_MPH = 0.5;
/** A 10:00 mile, core/run_plan.py RUN_PACE_KMH. */
export const RUN_PACE_DEFAULT_MPH = 6;

export const RUN_PACE_LABEL = t("Running pace");
export const RUN_PACE_HELP = t("Your easy pace on the flat, for the run's time. Climbs still slow it. Kept on this device.");

/** A pace in the picker's range on its half-mph steps, or null. */
export function paceOf(value: unknown): number | null {
  const mph = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  if (typeof mph !== "number" || !Number.isFinite(mph) || mph < RUN_PACE_MIN_MPH || mph > RUN_PACE_MAX_MPH) return null;
  return Number.isInteger(mph / RUN_PACE_STEP_MPH) ? mph : null;
}

export function readRunPace(store: KeyValueStore | null = browserStore()): number {
  try {
    return paceOf(store?.getItem(RUN_PACE_KEY) ?? null) ?? RUN_PACE_DEFAULT_MPH;
  } catch {
    return RUN_PACE_DEFAULT_MPH;
  }
}

/** Sent on the page when the pace changes, so the run shown is planned again at it (App.tsx). */
export const RUN_PACE_EVENT = "routemaker:run-pace";

export function writeRunPace(mph: number, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(RUN_PACE_KEY, String(mph));
  } catch {
    // Blocked site data: the pace holds for this visit only.
  }
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(RUN_PACE_EVENT, { detail: mph }));
}

/** Mph as the API's km/h, to a tenth. */
export const paceKmh = (mph: number): number => Math.round(mph * KMH_PER_MPH * 10) / 10;

/** Minutes and seconds a unit at `kmh`, a mile (`perKm` false) or a kilometre: "10:00". */
export function paceText(mph: number, perKm = false): string {
  const seconds = Math.round(perKm ? 3600 / (mph * KMH_PER_MPH) : 3600 / mph);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** The picker's choices: each pace as "10:00 /mi (6:13 /km)", miles first, keyed by its mph. */
export function paceOptions(): (readonly [string, string])[] {
  const out: (readonly [string, string])[] = [];
  for (let mph = RUN_PACE_MIN_MPH; mph <= RUN_PACE_MAX_MPH; mph += RUN_PACE_STEP_MPH) {
    const vars = { mile: paceText(mph), km: paceText(mph, true) };
    out.push([String(mph), metricFirst() ? t("{km} per km ({mile} per mile)", vars) : t("{mile} per mile ({km} per km)", vars)]);
  }
  return out;
}
