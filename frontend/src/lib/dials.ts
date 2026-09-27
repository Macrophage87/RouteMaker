/**
 * The planner's two sliders, its ride-time choice, and Cargo Bike's load.
 *
 * The API owns what each position does (src/core/presets.py); this is where
 * each slider starts on each ride type, what its ends and middle are called,
 * and how a position travels in the link. The starts are the API's own
 * (`Preset.stress`, `Preset.hills`, `CARGO_CARRYING_STRESS`), repeated here
 * so the sliders can sit at them before any route has come back; every
 * route's `dials` says what the API actually planned with.
 */
import type { PresetId } from "./presets.ts";

export type When = "weekend" | "weekday_rush" | "weekday_offpeak";
export type Carrying = "cargo" | "people";

export interface Dials {
  stress: number;
  hills: number;
  /** `null` is "when I'm planning": the setting of the moment, worked out by the API. */
  when: When | null;
  /** Cargo Bike only. */
  carrying: Carrying | null;
}

export const STRESS_MIN = 0;
export const STRESS_MAX = 100;
export const HILLS_MIN = -100;
export const HILLS_MAX = 100;

interface Start {
  stress: number;
  hills: number;
  /** Mass Ride's hills slider stops at the fastest time (PLAN: the seek half is disabled). */
  seek: boolean;
  carrying?: Record<Carrying, number>;
}

export const STARTS: Record<PresetId, Start> = {
  default: { stress: 75, hills: 0, seek: true },
  trailmaxxing: { stress: 100, hills: 0, seek: true },
  "group-ride": { stress: 50, hills: -50, seek: true },
  "mass-ride": { stress: 0, hills: -95, seek: false },
  "mountain-goat": { stress: 50, hills: 100, seek: true },
  gravel: { stress: 50, hills: 0, seek: true },
  fast: { stress: 10, hills: 0, seek: true },
  cargo: { stress: 75, hills: -60, seek: true, carrying: { cargo: 75, people: 95 } },
  ebike: { stress: 75, hills: -50, seek: true },
};

export const WHENS: readonly { id: When; label: string }[] = [
  { id: "weekend", label: "Weekend" },
  { id: "weekday_rush", label: "Weekday rush" },
  { id: "weekday_offpeak", label: "Weekday off-hours" },
];

export const CARRYINGS: readonly { id: Carrying; label: string; hint: string }[] = [
  { id: "cargo", label: "Carrying cargo", hint: "Quiet roads and bike lanes, gentle grades." },
  {
    id: "people",
    label: "Carrying people",
    hint: "Paths and protected lanes; busy streets only where there is no other way.",
  },
];

export function hillsMax(preset: PresetId): number {
  return STARTS[preset].seek ? HILLS_MAX : 0;
}

export function carries(preset: PresetId): boolean {
  return STARTS[preset].carrying !== undefined;
}

/** Where the sliders start on a ride type, for what the bike carries. */
export function startDials(preset: PresetId, carrying: Carrying | null = null, when: When | null = null): Dials {
  const start = STARTS[preset];
  const load = start.carrying ? (carrying ?? "cargo") : null;
  return {
    stress: load && start.carrying ? start.carrying[load] : start.stress,
    hills: start.hills,
    when,
    carrying: load,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** A position the API will take for this ride type, whatever a link said. */
export function fitDials(preset: PresetId, dials: Partial<Dials>): Dials {
  const start = startDials(preset, dials.carrying ?? null, dials.when ?? null);
  const stress = typeof dials.stress === "number" && Number.isFinite(dials.stress) ? dials.stress : start.stress;
  const hills = typeof dials.hills === "number" && Number.isFinite(dials.hills) ? dials.hills : start.hills;
  return {
    stress: clamp(stress, STRESS_MIN, STRESS_MAX),
    hills: clamp(hills, HILLS_MIN, hillsMax(preset)),
    when: start.when,
    carrying: start.carrying,
  };
}

/** The request's dial fields. `when` is left out when the API is to work it out. */
export function dialFields(dials: Dials): Record<string, string | number> {
  const fields: Record<string, string | number> = { stress: dials.stress, hills: dials.hills };
  if (dials.when) fields.when = dials.when;
  if (dials.carrying) fields.carrying = dials.carrying;
  return fields;
}

/** The words for a stress position: both ends and the middle are named. */
export function stressWords(stress: number): string {
  if (stress <= 10) return "Most direct legal route";
  if (stress < 40) return "Direct, some busy streets";
  if (stress <= 60) return "Balanced";
  if (stress < 90) return "Prefers quiet streets and paths";
  return "Low-stress only, unless there is no other way";
}

export function hillsWords(hills: number): string {
  if (hills <= -80) return "Avoids hills";
  if (hills < -10) return "Gentler grades";
  if (hills <= 10) return "Fastest time";
  if (hills < 80) return "Some extra climbing";
  return "Seeks hills";
}

export function isWhen(value: unknown): value is When {
  return typeof value === "string" && WHENS.some((w) => w.id === value);
}

export function isCarrying(value: unknown): value is Carrying {
  return value === "cargo" || value === "people";
}
