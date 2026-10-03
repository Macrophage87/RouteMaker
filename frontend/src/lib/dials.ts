/**
 * The planner's two sliders, its ride-time choice, and Cargo Bike's load.
 *
 * The API owns what each position does (src/core/presets.py); this is where
 * each slider starts on each ride type, what its ends and middle are called,
 * and how a position travels in the link. The starts are the API's own
 * (`Preset.stress`, `Preset.hills`, `CARGO_CARRYING_STRESS`), repeated here
 * so the sliders can sit at them before any route has come back; every
 * route's `dials` says what the API actually planned with.
 * tests/test_presets.py reads STARTS and holds it equal to the API's table.
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
  /** Cargo Bike only: electric assist (e-bike rules, a faster pace, the same hills start). */
  assist: boolean;
  /**
   * "Avoid gravel" (OWNER-DECISIONS 91, 92, 111): steer off unpaved surfaces.
   * Any ride type, off by default on all of them; absent is off. It is about
   * the ride, not the bike, so it stays when the ride type changes.
   */
  avoidGravel?: boolean;
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
  /** Mass Ride's traffic slider is locked at the most direct roadway (owner, 2026-09-27). */
  stressMax?: number;
  /** Cargo Bike offers electric assist. */
  assist?: boolean;
  /**
   * Trailmaxxing alone favors trails (OWNER-DECISIONS 202): the API credits each
   * mile of trail (`Preset.trail_credit`), so the route may add miles to ride one.
   */
  trails?: boolean;
}

/**
 * Where the traffic slider's positions fall, after the rescale of 2026-10-01
 * (OWNER-DECISIONS 163 and 164; src/core/presets.py says why). The old 0-100
 * slider ran to its end at 90; the old positions now sit at 0-80, Default (the
 * old 90) at 70, and the new top end above 80 is the calm detour search.
 * tests/test_calm_slider.py and tests/test_presets.py hold these equal to the API's.
 */
export const STRESS_DEFAULT_AT = 70;
export const STRESS_TODAYS_TOP = 80;
/** Metres of detour accepted per metre of LTS 3 avoided at the top (a proposal for the owner). */
export const CALM_RATE_MAX = 10;
export const CALM_CURVE = 3;

/** How many metres of detour a position accepts per metre of LTS 3 avoided: 0 up to 80, then exponential. */
export function calmRate(stress: number): number {
  if (stress <= STRESS_TODAYS_TOP) return 0;
  const t = (Math.min(stress, STRESS_MAX) - STRESS_TODAYS_TOP) / (STRESS_MAX - STRESS_TODAYS_TOP);
  return Math.round((CALM_RATE_MAX * Math.expm1(CALM_CURVE * t)) / Math.expm1(CALM_CURVE) * 1000) / 1000;
}

export const STARTS: Record<PresetId, Start> = {
  default: { stress: 70, hills: 0, seek: true },
  trailmaxxing: { stress: 100, hills: 0, seek: true, trails: true },
  "group-ride": { stress: 40, hills: -50, seek: true },
  "mass-ride": { stress: 0, hills: -95, seek: false, stressMax: 0 },
  "mountain-goat": { stress: 40, hills: 100, seek: true },
  gravel: { stress: 40, hills: 0, seek: true },
  fast: { stress: 10, hills: 0, seek: true },
  cargo: { stress: 70, hills: -60, seek: true, carrying: { cargo: 70, people: 80 }, assist: true },
  ebike: { stress: 70, hills: -50, seek: true },
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
    // OWNER-DECISIONS 241: "Let's also call it passengers, as people bring dogs too."
    // The id stays "people", which links, saved plans and the API carry.
    label: "Cargo with passengers",
    hint: "People or pets aboard: paths and protected lanes; busy streets only where avoiding them takes much longer.",
  },
];

/** What the load is called in a sentence: "carrying cargo", "cargo with passengers" (the label, lower case). */
export function carryingWords(id: string): string {
  return CARRYINGS.find((c) => c.id === id)?.label.toLowerCase() ?? id;
}

export function hillsMax(preset: PresetId): number {
  return STARTS[preset].seek ? HILLS_MAX : 0;
}

export function stressMax(preset: PresetId): number {
  return STARTS[preset].stressMax ?? STRESS_MAX;
}

export function offersAssist(preset: PresetId): boolean {
  return STARTS[preset].assist === true;
}

/** Whether the ride type favors trails (Trailmaxxing's trail credit). */
export function favorsTrails(preset: PresetId): boolean {
  return STARTS[preset].trails === true;
}

export function carries(preset: PresetId): boolean {
  return STARTS[preset].carrying !== undefined;
}

/** Where the sliders start on a ride type, for what the bike carries. */
export function startDials(
  preset: PresetId,
  carrying: Carrying | null = null,
  when: When | null = null,
  assist = false,
): Dials {
  const start = STARTS[preset];
  const load = start.carrying ? (carrying ?? "cargo") : null;
  return {
    stress: load && start.carrying ? start.carrying[load] : start.stress,
    // Electric assist does not soften the hills start: a heavy cargo bike's
    // motor rarely cancels a climb (the owner, 2026-09-27).
    hills: start.hills,
    when,
    carrying: load,
    assist: offersAssist(preset) && assist,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** A position the API will take for this ride type, whatever a link said. */
export function fitDials(preset: PresetId, dials: Partial<Dials>): Dials {
  const start = startDials(preset, dials.carrying ?? null, dials.when ?? null, dials.assist === true);
  const stress = typeof dials.stress === "number" && Number.isFinite(dials.stress) ? dials.stress : start.stress;
  const hills = typeof dials.hills === "number" && Number.isFinite(dials.hills) ? dials.hills : start.hills;
  return {
    stress: clamp(stress, STRESS_MIN, stressMax(preset)),
    hills: clamp(hills, HILLS_MIN, hillsMax(preset)),
    when: start.when,
    carrying: start.carrying,
    assist: start.assist,
    ...(dials.avoidGravel === true ? { avoidGravel: true } : {}),
  };
}

/** The request's dial fields. `when` is left out when the API is to work it out. */
export function dialFields(dials: Dials): Record<string, string | number | boolean> {
  const fields: Record<string, string | number | boolean> = { stress: dials.stress, hills: dials.hills };
  if (dials.when) fields.when = dials.when;
  if (dials.carrying) fields.carrying = dials.carrying;
  if (dials.assist) fields.assist = true;
  if (dials.avoidGravel) fields.avoid_gravel = true;
  return fields;
}

/**
 * The bottom of the traffic slider is traffic tolerant, not "fastest" (the
 * owner, 2026-09-28: "Let's make the current setting a traffic tolerant one
 * and then build a full fastest custom. There should be a warning going at
 * this setting."). At or below this position the panel and the route summary
 * say so.
 */
export const TRAFFIC_TOLERANT_MAX = 10;
export const TRAFFIC_TOLERANT_WARNING = "Traffic tolerant: this route may use busy, fast roads.";

/** Whether a position warns: the bottom of the slider, on a ride type whose slider moves. */
export function warnsTrafficTolerant(preset: PresetId, stress: number): boolean {
  return stressMax(preset) > 0 && stress <= TRAFFIC_TOLERANT_MAX;
}

/** Where the calm detour words change: the old top is "low-stress", past it the route goes out of its way. */
export const CALM_FAR_FROM = 95;

/** The words for a stress position: both ends and the middle are named. */
export function stressWords(stress: number): string {
  if (stress <= TRAFFIC_TOLERANT_MAX) return "Traffic tolerant";
  if (stress < 30) return "Direct, some busy streets";
  if (stress <= 50) return "Balanced";
  if (stress < 75) return "Prefers quiet streets and paths";
  if (stress <= STRESS_TODAYS_TOP) return "Low-stress, unless avoiding busy streets takes much longer";
  if (stress < CALM_FAR_FROM) return "Calm: will go well out of the way to avoid busy roads";
  return "Calmest: detours many times the straight line to avoid busy roads";
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
