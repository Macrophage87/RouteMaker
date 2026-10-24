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
import type { LonLat } from "./geo.ts";
import { isTransit, usesBikeshare, type PresetId } from "./presets.ts";
import { DEFAULT_MTB_LEVEL, defaultMtbPreferred, fitMtbLevel, mtbLevelOf, mtbPreferredOf } from "./mtbMode.ts";

export type When = "weekend" | "weekday_rush" | "weekday_offpeak" | "night";
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
   * "Keep to roads, not trails" (OWNER-DECISIONS 463, 463b; 2026-09-26, "Every type,
   * roadways ok"): plan on roadways only, on any ride type, e-bike rides included (463a). Absent is off (trails allowed), except on
   * Mass Ride, which is always trails off (`trailsOffLocked`). It is about the ride,
   * so it stays when the ride type changes.
   */
  trailsOff?: boolean;
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
  /**
   * Mountain Bike only (docs/MTB-TOPO-PLAN.md, slice 6): the hardest trail level, 1 (green) to 4 (red).
   * Absent is the default, level 2 (lib/mtbMode.ts DEFAULT_MTB_LEVEL).
   */
  mtbLevel?: number;
  /**
   * Mountain Bike only (docs/MTB-TOPO-PLAN.md, second pass): the preferred trail level, 1 to 4, never
   * above `mtbLevel`. Absent is the default: 2, or `mtbLevel` where that is lower (lib/mtbMode.ts
   * mtbPreferredOf), so an older link with only the hardest level plans as it did.
   */
  mtbPreferred?: number;
  /** Bikeshare only: the bike. Absent is classic. */
  bike?: Bike;
  /**
   * Bikeshare e-bike only (OWNER-DECISIONS 244): end outside a dock, at the destination, where
   * the operator's zone data allows it. Absent is a dock.
   */
  ending?: Ending;
  /**
   * Bikeshare only (OWNER-DECISIONS 466a): the station the rider chose to take a bike from, and
   * the one to return it to, from the nearest-stations lists. Session only: they are added to a
   * request (lib/stations.ts withStations) and are in no link, because a station's bikes change
   * by the minute.
   */
  pickupStation?: string;
  dropoffStation?: string;
  /**
   * The transit ride types only (TRANSIT-ASSIST): the option the rider chose from the answer's
   * list, by its key (`transit.options[].key`). Session only, like the stations: added to a
   * request (lib/transit.ts withTransitOption), in no link, since a timetable moves on.
   */
  transitOption?: string;
  /**
   * "Route through anyway" (v0.7.0, lib/closureMap.ts): the closures the rider chose to route through, for this
   * plan only. Session only, like the stations: added to the route request (lib/api.ts requestRoute), in no link,
   * and not in dialFields (the other endpoints do not take it).
   */
  closureBypass?: string[];
  /**
   * v0.9.1, Go and a ride: only the closures known to be on, leaving out DDOT's permits, which say a road may be
   * closed (Stephen, 2026-10-19: "They aren't as useful for on the go routing, but worth keeping for future ride
   * planning"). Plan leaves it off and keeps them. Session only, like closureBypass: in the request, never a link.
   */
  closuresNow?: boolean;
  /**
   * The transit ride types only (v0.7.0, Novice and Nervous): the bike legs planned as Novice and Nervous
   * plans them, for a novice rider offered transit where only a busy road connects. In the link; absent is off.
   */
  noviceLegs?: boolean;
  /**
   * With `noviceLegs` (v0.11.0): where the Novice route's busiest stretch begins and ends (its `novice.busiest`),
   * sent as novice_hop, so the transit trips also hop past it (board near its start, get off near its end). For the
   * trip the offer was taken on only (App's noviceHopPick, as transitOption): request only, never the link.
   */
  noviceHop?: [LonLat, LonLat];
  /**
   * "Anticipated ride size" (PLAN items 128, 129, 139), Mass Ride only: the riders expected,
   * 100 to 2,000. It sets the group's length, which the corker load is counted over (the
   * owner, 2026-10-10: "Corkers were intended to also have a rollback based on the length of
   * the ride"). Absent is RIDE_SIZE_DEFAULT. It does not change the route, so it is never
   * sent to the API (dialFields); it rides in the link (planHash.ts).
   */
  rideSize?: number;
}

/** The ride size's range and default, riders (PLAN item 129: the owner's typical range; 128: a proposed 500). */
export const RIDE_SIZE_MIN = 100;
export const RIDE_SIZE_MAX = 2_000;
export const RIDE_SIZE_DEFAULT = 500;
export const RIDE_SIZE_STEP = 50;

/** Whether the ride size applies: Mass Ride only. */
export function offersRideSize(preset: PresetId): boolean {
  return preset === "mass-ride";
}

/** A ride size the chart will take: in range, to the slider's step; undefined where it is not a number. */
export function fitRideSize(riders: unknown): number | undefined {
  if (typeof riders !== "number" || !Number.isFinite(riders)) return undefined;
  const stepped = Math.round(riders / RIDE_SIZE_STEP) * RIDE_SIZE_STEP;
  return Math.min(RIDE_SIZE_MAX, Math.max(RIDE_SIZE_MIN, stepped));
}

/** The ride size a Mass Ride is drawn for: the rider's, or the default. */
export function rideSizeOf(dials: Pick<Dials, "rideSize">): number {
  return fitRideSize(dials.rideSize) ?? RIDE_SIZE_DEFAULT;
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
  /**
   * Mountain Goat alone: the slider's right half seeks climbs. On every other ride type it means
   * "fine with hills" (FOLLOWUP-HILLS-TOLERATE, OWNER-DECISIONS 242; `core.presets.Preset.hills_tolerate`).
   */
  climbs?: boolean;
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

/** The most metres a calm detour may add for each metre of LTS 3 it avoids below the top
 * (OWNER-DECISIONS 435, the owner's "One rule"): 1 + 4 x the calm rate over its top, as
 * `core.refine.worth_ratio`; 5 at the top. */
export const WORTH_DEFAULT = 5;
export function worthRatio(stress: number): number {
  return 1 + ((WORTH_DEFAULT - 1) * calmRate(stress)) / CALM_RATE_MAX;
}

export const STARTS: Record<PresetId, Start> = {
  default: { stress: 70, hills: 0, seek: true },
  trailmaxxing: { stress: 100, hills: 0, seek: true },
  "group-ride": { stress: 40, hills: -50, seek: true },
  "mass-ride": { stress: 0, hills: -95, seek: false, stressMax: 0 },
  "mountain-goat": { stress: 40, hills: 100, seek: true, climbs: true },
  // Slice 6: the old top of the traffic slider, hills at "fine with hills" (core.presets MTB_HILLS).
  "mountain-bike": { stress: 80, hills: 50, seek: true },
  gravel: { stress: 40, hills: 0, seek: true },
  // A strong rider: an LT1 grade of about 11% (`core.presets.FAST_HILLS`; Stephen, 2026-10-23: "More for fast").
  fast: { stress: 10, hills: 40, seek: true },
  cargo: { stress: 70, hills: -60, seek: true, carrying: { cargo: 70, people: 80 }, assist: true },
  // Toward "fine with hills" (242): `core.presets.EBIKE_HILLS`.
  ebike: { stress: 70, hills: 50, seek: true },
  // The classic bike's start; the e-bike's hills start is BIKESHARE_BIKES.ebike.hills.
  bikeshare: { stress: 80, hills: -60, seek: true, assist: true },
  // v0.7.0 Novice and Nervous: the top of the traffic slider, hills at Cargo's gentle -60 (core.presets NOVICE_HILLS).
  novice: { stress: 100, hills: -60, seek: true },
  // The transit ride types' bike legs start as Default's own bike and Bikeshare's classic (core.presets).
  "bike-transit": { stress: 70, hills: 0, seek: true },
  "bikeshare-transit": { stress: 80, hills: -60, seek: true },
  // REBALANCE-RIDE: Bikeshare's own start (core.presets REBALANCE), with its bike choice.
  rebalance: { stress: 80, hills: -60, seek: true, assist: true },
};

/** A ride time's label inside a sentence: only its first letter lowered, so "PM"
 * and "AM" keep the capitals a screen reader says as letters. */
export function whenInSentence(label: string): string {
  return label.charAt(0).toLowerCase() + label.slice(1);
}

export const WHENS: readonly { id: When; label: string }[] = [
  { id: "weekend", label: "Weekend" },
  { id: "weekday_rush", label: "Weekday rush" },
  { id: "weekday_offpeak", label: "Weekday off-hours" },
  // OWNER-DECISIONS 469c: 9 PM to 7 AM on any day; busy-road junctions count for less.
  { id: "night", label: "Night, 9 PM to 7 AM" },
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

/** Whether the hills slider's right half seeks climbs (Mountain Goat) rather than "fine with hills" (242). */
export function seeksClimbs(preset: PresetId): boolean {
  return STARTS[preset].climbs === true;
}

export function hillsMax(preset: PresetId): number {
  return STARTS[preset].seek ? HILLS_MAX : 0;
}

export function stressMax(preset: PresetId): number {
  return STARTS[preset].stressMax ?? STRESS_MAX;
}

/** Ride types that are always trails off: the switch shows on and cannot change (Mass Ride). */
export function trailsOffLocked(preset: PresetId): boolean {
  return preset === "mass-ride";
}

/** Whether the ride is planned trails off: the rider's switch, or a ride type that always is. */
export function trailsAreOff(preset: PresetId, dials: Pick<Dials, "trailsOff">): boolean {
  return trailsOffLocked(preset) || dials.trailsOff === true;
}

export function offersAssist(preset: PresetId): boolean {
  // Bikeshare's assist is its bike choice, not Cargo Bike's toggle.
  return STARTS[preset].assist === true && !usesBikeshare(preset);
}

/**
 * Where each bike's hills slider starts on Bikeshare: a classic is hill-averse (as Cargo
 * Bike's), an e-bike barely minds a hill. `core.presets.BIKESHARE_BIKES`, which
 * tests/test_presets.py holds this to.
 */
export const BIKESHARE_HILLS: Record<Bike, number> = { classic: -60, ebike: -20 };

export function offersBike(preset: PresetId): boolean {
  return usesBikeshare(preset);
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
/** Novice and Nervous's shorter ceiling (`core.presets.NOVICE_CEILING_RATIO`, v0.7.0). */
export const NOVICE_CEILING_RATIO = 1.4;
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
    // Only an e-bike can end outside a dock, and never on Rebalance Ride (it ends where a bike is needed).
    ...(start.bike === "ebike" && dials.ending === "outside_dock" && preset !== "rebalance" ? { ending: "outside_dock" as const } : {}),
    ...(dials.avoidGravel === true ? { avoidGravel: true } : {}),
    ...(dials.trailsOff === true ? { trailsOff: true } : {}),
    ...(fitTarget(dials.targetDistanceM) !== undefined ? { targetDistanceM: fitTarget(dials.targetDistanceM) } : {}),
    ...(dials.loop === true ? { loop: true } : {}),
    ...(isTransit(preset) && dials.noviceLegs === true ? { noviceLegs: true } : {}),
    ...(isTransit(preset) && dials.noviceLegs === true && dials.noviceHop ? { noviceHop: dials.noviceHop } : {}),
    // The level, on Mountain Bike only, and only when it is not the default (the link stays short).
    ...(preset === "mountain-bike" && fitMtbLevel(dials.mtbLevel) !== undefined && fitMtbLevel(dials.mtbLevel) !== DEFAULT_MTB_LEVEL
      ? { mtbLevel: fitMtbLevel(dials.mtbLevel) }
      : {}),
    // The preferred level likewise, held to the hardest; left out where it is the default (min(2, hardest)).
    ...(preset === "mountain-bike" && fitMtbLevel(dials.mtbPreferred) !== undefined && mtbPreferredOf(dials) !== defaultMtbPreferred(mtbLevelOf(dials))
      ? { mtbPreferred: mtbPreferredOf(dials) }
      : {}),
    ...(offersRideSize(preset) && fitRideSize(dials.rideSize) !== undefined && fitRideSize(dials.rideSize) !== RIDE_SIZE_DEFAULT
      ? { rideSize: fitRideSize(dials.rideSize) }
      : {}),
  };
}

/** The request's dial fields. `when` is left out when the API is to work it out. */
export function dialFields(dials: Dials): Record<string, string | number | boolean | LonLat[]> {
  const fields: Record<string, string | number | boolean | LonLat[]> = { stress: dials.stress, hills: dials.hills };
  if (dials.when) fields.when = dials.when;
  if (dials.carrying) fields.carrying = dials.carrying;
  if (dials.assist) fields.assist = true;
  if (dials.avoidGravel) fields.avoid_gravel = true;
  if (dials.trailsOff) fields.trails_off = true;
  const target = fitTarget(dials.targetDistanceM);
  if (target !== undefined) fields.target_distance_m = target;
  const weight = fitWeight(dials.systemWeightKg);
  // The API takes whole kilograms (core.api, StrictInt).
  if (weight !== undefined) fields.system_weight_kg = Math.round(weight);
  if (dials.loop) fields.loop = true;
  // Mountain Bike's level (fitDials keeps it on that ride type alone); absent is level 2.
  const level = fitMtbLevel(dials.mtbLevel);
  if (level !== undefined) fields.mtb_level = level;
  // The preferred level (fitDials holds it to the hardest); absent is min(2, the hardest), as the API's.
  const preferred = fitMtbLevel(dials.mtbPreferred);
  if (preferred !== undefined) fields.mtb_preferred = Math.min(preferred, level ?? DEFAULT_MTB_LEVEL);
  if (dials.bike) fields.bike = dials.bike;
  if (dials.bike === "ebike" && dials.ending === "outside_dock") fields.ending = "outside_dock";
  if (dials.bike && dials.pickupStation) fields.pickup_station = dials.pickupStation;
  if (dials.bike && dials.dropoffStation && dials.ending !== "outside_dock") {
    fields.dropoff_station = dials.dropoffStation;
  }
  if (dials.transitOption) fields.transit_option = dials.transitOption;
  if (dials.noviceLegs) fields.novice_legs = true;
  if (dials.noviceLegs && dials.noviceHop) fields.novice_hop = dials.noviceHop;
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

/** The rider's LT1 grade (percent) the hills slider sets: 1% at full avoid to 15% at the far end, in a straight line
 * (`routemaker.hill_cost.lt1_grade_for`; Stephen, 2026-10-23: "Maybe 0-15% ... or 1-15"). */
export const LT1_GRADE_MIN_PCT = 1;
export const LT1_GRADE_MAX_PCT = 15;
export function lt1GradePct(hills: number): number {
  const share = (Math.min(Math.max(hills, HILLS_MIN), HILLS_MAX) - HILLS_MIN) / (HILLS_MAX - HILLS_MIN);
  return LT1_GRADE_MIN_PCT + (LT1_GRADE_MAX_PCT - LT1_GRADE_MIN_PCT) * share;
}

/** The hills dial's grade, whole percent: its place on the slider, which shows grade percent. */
export function hillsGradePosition(hills: number): number {
  return Math.round(lt1GradePct(hills));
}

/** The hills dial at a whole-percent grade on the slider (the inverse of `hillsGradePosition`). */
export function hillsAtGrade(pct: number): number {
  const share = (pct - LT1_GRADE_MIN_PCT) / (LT1_GRADE_MAX_PCT - LT1_GRADE_MIN_PCT);
  return Math.round(HILLS_MIN + (HILLS_MAX - HILLS_MIN) * Math.min(Math.max(share, 0), 1));
}

/** The hills slider in words: the grade it sets, whole percent; Mountain Goat's right half seeks climbs. */
export function hillsWords(hills: number, climbs: boolean): string {
  if (climbs && hills > 10) return hills < 80 ? "Some extra climbing" : "Seeks hills";
  return `Easy up to ${Math.round(lt1GradePct(hills))}%`;
}

export function isWhen(value: unknown): value is When {
  return typeof value === "string" && WHENS.some((w) => w.id === value);
}

export function isCarrying(value: unknown): value is Carrying {
  return value === "cargo" || value === "people";
}
