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
/** Bikeshare's bike (OWNER-DECISIONS 243): the operator's classic, or its e-bike. */
export type Bike = "classic" | "ebike";
/** Bikeshare e-bike's ending (OWNER-DECISIONS 244): at a dock, or at the destination outside one. */
export type Ending = "dock" | "outside_dock";

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
  /**
   * "Target distance" (OWNER-DECISIONS 256, 271), in metres: a soft goal. The planner
   * finds the least stressful route at or under it, and goes past it only where the
   * extra miles avoid enough stress, never past `TARGET_CEILING_RATIO` times it.
   * Optional, and only at the top of the traffic slider (`offersTargetDistance`);
   * absent is no target, with a ceiling of 1.6 times the router's own route
   * (`core.presets.DEFAULT_CEILING_RATIO`).
   */
  targetDistanceM?: number;
  /**
   * "System weight" (OWNER-DECISIONS 264), in kilograms: rider, bike and load, which
   * the effort the Hills slider avoids is weighed by. Optional, and only at the top
   * of the traffic slider; absent is the default (`SYSTEM_WEIGHT_KG`, or
   * `PASSENGERS_WEIGHT_KG` for Cargo with passengers).
   */
  systemWeightKg?: number;
  /** "Make it a loop" (OWNER-DECISIONS 266); a ride ending where it starts is one without it. */
  loop?: boolean;
  /** Bikeshare only: the bike. Absent is classic. */
  bike?: Bike;
  /**
   * Bikeshare e-bike only (OWNER-DECISIONS 244): end outside a dock, at the destination, where
   * the operator's zone data allows it. Absent is a dock.
   */
  ending?: Ending;
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
  trailmaxxing: { stress: 100, hills: 0, seek: true },
  "group-ride": { stress: 40, hills: -50, seek: true },
  "mass-ride": { stress: 0, hills: -95, seek: false, stressMax: 0 },
  "mountain-goat": { stress: 40, hills: 100, seek: true },
  gravel: { stress: 40, hills: 0, seek: true },
  fast: { stress: 10, hills: 0, seek: true },
  cargo: { stress: 70, hills: -60, seek: true, carrying: { cargo: 70, people: 80 }, assist: true },
  ebike: { stress: 70, hills: -50, seek: true },
  // The classic bike's start; the e-bike's hills start is BIKESHARE_BIKES.ebike.hills.
  bikeshare: { stress: 80, hills: -60, seek: true, assist: true },
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
  // Bikeshare's assist is its bike choice, not Cargo Bike's toggle.
  return STARTS[preset].assist === true && preset !== "bikeshare";
}

/**
 * Where each bike's hills slider starts on Bikeshare: a classic is hill-averse (as Cargo
 * Bike's), an e-bike barely minds a hill. `core.presets.BIKESHARE_BIKES`, which
 * tests/test_presets.py holds this to.
 */
export const BIKESHARE_HILLS: Record<Bike, number> = { classic: -60, ebike: -20 };

export function offersBike(preset: PresetId): boolean {
  return preset === "bikeshare";
}

export function isBike(value: unknown): value is Bike {
  return value === "classic" || value === "ebike";
}

export function isEnding(value: unknown): value is Ending {
  return value === "dock" || value === "outside_dock";
}

/**
 * What the API takes for a target distance (metres): `core.presets.TARGET_DISTANCE_MIN_M`
 * and `TARGET_DISTANCE_MAX_M`, and the ceilings (`DEFAULT_CEILING_RATIO`,
 * `TARGET_CEILING_RATIO`), which tests/test_plan_constants.py holds this to.
 */
export const TARGET_MIN_M = 1_000;
export const TARGET_MAX_M = 1_000_000;
export const DEFAULT_CEILING_RATIO = 1.6;
export const TARGET_CEILING_RATIO = 1.25;
/** The system weight's range and defaults (kg): `routemaker.effort`, which tests/test_presets.py holds this to. */
// OWNER-DECISIONS 337: "The weight range must include everyone", for every ride type;
// 338: a total outside it is planned with the nearer limit, not refused; 352: silently,
// and the top raised to 700 kg (1,543 lb), "people who ride pedicabs with 2
// passengers".
export const SYSTEM_WEIGHT_MIN_KG = 25;
export const SYSTEM_WEIGHT_MAX_KG = 700;
export const SYSTEM_WEIGHT_KG = 90;
export const PASSENGERS_WEIGHT_KG = 120;

/**
 * A system weight the API will take, to a tenth of a kilogram, or undefined. The
 * tenth is kept so pounds typed come back as typed (lib/dialsPanel.ts parseWeight);
 * the request sends it rounded to whole kilograms (dialFields), which the API's
 * range is checked on.
 */
export function fitWeight(kg: unknown): number | undefined {
  if (typeof kg !== "number" || !Number.isFinite(kg) || kg <= 0) return undefined;
  // Outside the range, the nearer limit (OWNER-DECISIONS 338).
  return Math.min(SYSTEM_WEIGHT_MAX_KG, Math.max(SYSTEM_WEIGHT_MIN_KG, Math.round(kg * 10) / 10));
}

/** Whether the "Target distance" dial applies: the top of the traffic slider, on a ride type whose slider moves. */
export function offersTargetDistance(preset: PresetId, stress: number): boolean {
  return stressMax(preset) >= STRESS_MAX && stress >= STRESS_MAX;
}

/** A target distance the API will take, or undefined (not a number, or out of range). */
export function fitTarget(metres: unknown): number | undefined {
  if (typeof metres !== "number" || !Number.isFinite(metres)) return undefined;
  const whole = Math.round(metres);
  return whole >= TARGET_MIN_M && whole <= TARGET_MAX_M ? whole : undefined;
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
  bike: Bike | null = null,
): Dials {
  const start = STARTS[preset];
  const load = start.carrying ? (carrying ?? "cargo") : null;
  const chosen: Bike | null = offersBike(preset) ? (bike ?? "classic") : null;
  return {
    stress: load && start.carrying ? start.carrying[load] : start.stress,
    // Electric assist does not soften the hills start: a heavy cargo bike's
    // motor rarely cancels a climb (the owner, 2026-09-27). Bikeshare's e-bike does:
    // hills barely count on it.
    hills: chosen ? BIKESHARE_HILLS[chosen] : start.hills,
    when,
    carrying: load,
    assist: offersAssist(preset) && assist,
    ...(chosen ? { bike: chosen } : {}),
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** A position the API will take for this ride type, whatever a link said. */
export function fitDials(preset: PresetId, dials: Partial<Dials>): Dials {
  const start = startDials(
    preset,
    dials.carrying ?? null,
    dials.when ?? null,
    dials.assist === true,
    isBike(dials.bike) ? dials.bike : null,
  );
  const stress = typeof dials.stress === "number" && Number.isFinite(dials.stress) ? dials.stress : start.stress;
  const hills = typeof dials.hills === "number" && Number.isFinite(dials.hills) ? dials.hills : start.hills;
  return {
    stress: clamp(stress, STRESS_MIN, stressMax(preset)),
    hills: clamp(hills, HILLS_MIN, hillsMax(preset)),
    when: start.when,
    carrying: start.carrying,
    assist: start.assist,
    ...(start.bike ? { bike: start.bike } : {}),
    // Only an e-bike can end outside a dock.
    ...(start.bike === "ebike" && dials.ending === "outside_dock" ? { ending: "outside_dock" as const } : {}),
    ...(dials.avoidGravel === true ? { avoidGravel: true } : {}),
    ...(fitTarget(dials.targetDistanceM) !== undefined ? { targetDistanceM: fitTarget(dials.targetDistanceM) } : {}),
    ...(dials.loop === true ? { loop: true } : {}),
  };
}

/** The request's dial fields. `when` is left out when the API is to work it out. */
export function dialFields(dials: Dials): Record<string, string | number | boolean> {
  const fields: Record<string, string | number | boolean> = { stress: dials.stress, hills: dials.hills };
  if (dials.when) fields.when = dials.when;
  if (dials.carrying) fields.carrying = dials.carrying;
  if (dials.assist) fields.assist = true;
  if (dials.avoidGravel) fields.avoid_gravel = true;
  const target = fitTarget(dials.targetDistanceM);
  if (target !== undefined) fields.target_distance_m = target;
  const weight = fitWeight(dials.systemWeightKg);
  // The API takes whole kilograms (core.api, StrictInt).
  if (weight !== undefined) fields.system_weight_kg = Math.round(weight);
  if (dials.loop) fields.loop = true;
  if (dials.bike) fields.bike = dials.bike;
  if (dials.bike === "ebike" && dials.ending === "outside_dock") fields.ending = "outside_dock";
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
  if (stress < STRESS_MAX) return "Calmest: detours many times the straight line to avoid busy roads";
  return "Calmest: the least stressful route, aiming at your target distance";
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
