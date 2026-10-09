/**
 * The plan in the page's URL fragment, so a link opens the same route.
 *
 * The fragment and not the query string: a fragment never leaves the browser,
 * so the points a rider is looking at reach no server log - which matters when
 * some rides are unpermitted. Nothing here is saved; saving is for signed-in
 * riders (owner decision, 2026-09-26).
 */
import { MAX_POINTS, insideCoverage, type LonLat } from "./geo.ts";
import { parsePreset, type PresetId } from "./presets.ts";
import { STRESS_DEFAULT_AT, fitDials, isCarrying, isWhen, type Dials } from "./dials.ts";
import { METRES_PER_MILE } from "./format.ts";

/**
 * The link's version. It stays 2 for the target distance (OWNER-DECISIONS 256, 271):
 * `targetmi` is a new field that an older link does not have and means none, and no
 * field a link already carried changes what it names. 2 is the traffic slider after its rescale of 2026-10-01
 * (OWNER-DECISIONS 163): the old 0-100 now sits at 0-80, the old 90 (Default)
 * at 70, and above 80 is the calm detour search. A link with no `v` is from
 * before, and its `stress` is mapped onto the new scale (`stressFromV1`), so an
 * old Default link still opens Default's route and an old Trailmaxxing link the
 * old top, not the new calm search (review r1, B4).
 */
export const PLAN_VERSION = "2";

/** The old slider's position on the new one: old x 70/90 up to 90, then 70 + (old - 90). */
export function stressFromV1(old: number): number {
  const OLD_DEFAULT = 90;
  if (old <= OLD_DEFAULT) return Math.round((old * STRESS_DEFAULT_AT) / OLD_DEFAULT);
  return STRESS_DEFAULT_AT + Math.round(old - OLD_DEFAULT);
}

export interface Plan {
  points: LonLat[];
  preset: PresetId;
  /** The sliders, the ride time and Cargo Bike's load (dials.ts). */
  dials: Dials;
}

export function encodePlan(points: readonly LonLat[], preset: PresetId, dials?: Dials): string {
  const params = new URLSearchParams();
  if (points.length) params.set("p", points.map(([lon, lat]) => `${lon.toFixed(5)},${lat.toFixed(5)}`).join(";"));
  params.set("preset", preset);
  if (dials) {
    params.set("v", PLAN_VERSION);
    params.set("stress", String(dials.stress));
    params.set("hills", String(dials.hills));
    if (dials.when) params.set("when", dials.when);
    if (dials.carrying) params.set("carrying", dials.carrying);
    if (dials.assist) params.set("assist", "1");
    if (dials.avoidGravel) params.set("avoidgravel", "1");
    // "Trails off" (OWNER-DECISIONS 463). Absent is trails on, except on Mass Ride, which is always off.
    if (dials.trailsOff) params.set("trailsoff", "1");
    // The target distance in miles, to a tenth. Absent is none; an older link has none.
    if (dials.targetDistanceM) params.set("targetmi", (dials.targetDistanceM / METRES_PER_MILE).toFixed(1));
    // Never the rider and bike weight (OWNER-DECISIONS 313): it is private.
    // "Make it a loop" (OWNER-DECISIONS 266); absent is off.
    if (dials.loop) params.set("loop", "1");
  }
  return `#${params.toString().replaceAll("%2C", ",").replaceAll("%3B", ";")}`;
}

function numberOrUndefined(value: string | null): number | undefined {
  if (value === null || value.trim() === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

export function decodePlan(hash: string): Plan {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const points: LonLat[] = [];
  for (const pair of (params.get("p") ?? "").split(";")) {
    const parts = pair.split(",");
    if (parts.length !== 2) continue;
    const point: LonLat = [Number(parts[0]), Number(parts[1])];
    if (!Number.isFinite(point[0]) || !Number.isFinite(point[1]) || !insideCoverage(point)) continue;
    points.push(point);
    if (points.length === MAX_POINTS) break;
  }
  const preset = parsePreset(params.get("preset"));
  const when = params.get("when");
  const carrying = params.get("carrying");
  const linked = numberOrUndefined(params.get("stress"));
  const stress = linked === undefined || params.get("v") === PLAN_VERSION ? linked : stressFromV1(linked);
  const targetMiles = numberOrUndefined(params.get("targetmi"));
  const dials = fitDials(preset, {
    stress,
    targetDistanceM: targetMiles === undefined ? undefined : Math.round(targetMiles * METRES_PER_MILE),
    // An older link's "sysweight" is ignored (OWNER-DECISIONS 313).
    loop: params.get("loop") === "1",
    hills: numberOrUndefined(params.get("hills")),
    when: isWhen(when) ? when : null,
    carrying: isCarrying(carrying) ? carrying : null,
    assist: params.get("assist") === "1",
    avoidGravel: params.get("avoidgravel") === "1",
    trailsOff: params.get("trailsoff") === "1",
  });
  return { points, preset, dials };
}
