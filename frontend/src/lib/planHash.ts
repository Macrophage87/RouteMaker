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
import { fitDials, isCarrying, isWhen, type Dials } from "./dials.ts";

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
    params.set("stress", String(dials.stress));
    params.set("hills", String(dials.hills));
    if (dials.when) params.set("when", dials.when);
    if (dials.carrying) params.set("carrying", dials.carrying);
    if (dials.assist) params.set("assist", "1");
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
  const dials = fitDials(preset, {
    stress: numberOrUndefined(params.get("stress")),
    hills: numberOrUndefined(params.get("hills")),
    when: isWhen(when) ? when : null,
    carrying: isCarrying(carrying) ? carrying : null,
    assist: params.get("assist") === "1",
  });
  return { points, preset, dials };
}
