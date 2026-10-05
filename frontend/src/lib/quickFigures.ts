/**
 * The route summary's four quick figures and the stress bar's words
 * (OWNER-DECISIONS 312, mockup v3): how much of the route is paths and quiet
 * streets, how far it is on heavy traffic, how many stressful junctions it
 * passes, and how much is an off-road path. Each is words and a figure, never
 * a colour. Miles first, metric in brackets (formatDistance).
 *
 * All of it comes from fields the planner already returns (`stress_m`,
 * `facility_m`, `intersections`); nothing here asks for more.
 */
import { formatDistance } from "./format.ts";
import { junctionCounts } from "./intersectionMarkers.ts";
import type { RouteResponse } from "./api.ts";

export interface QuickFigure {
  key: "calm" | "heavy" | "junctions" | "path";
  label: string;
  value: string;
}

export const NOT_AVAILABLE = "Not available";

function metres(by: Record<string, number | undefined> | undefined, key: string): number {
  const value = by?.[key];
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

/** The share of the route (whole percent) on LTS 1 and 2, or null with no stress figures. */
export function calmPercent(stress: RouteResponse["stress_m"] | undefined): number | null {
  const all = ["1", "2", "3", "4", "5", "unknown"].reduce((sum, key) => sum + metres(stress, key), 0);
  if (!(all > 0)) return null;
  return Math.round(((metres(stress, "1") + metres(stress, "2")) / all) * 100);
}

/** The metres on LTS 4 and on roads marked legal but best avoided. */
export function heavyMetres(stress: RouteResponse["stress_m"] | undefined): number {
  return metres(stress, "4") + metres(stress, "5");
}

/** "1 very high, 3 higher", or "None"; "Not available" where the planner could not read the junctions. */
export function junctionFigure(intersections: RouteResponse["intersections"] | undefined): string {
  if (intersections == null) return NOT_AVAILABLE;
  const counts = junctionCounts(intersections);
  if (counts.total === 0) return "None";
  const parts: string[] = [];
  if (counts.red > 0) parts.push(`${counts.red} very high`);
  if (counts.orange > 0) parts.push(`${counts.orange} higher`);
  return parts.join(", ");
}

export function quickFigures(route: Pick<RouteResponse, "stress_m" | "facility_m" | "intersections">): QuickFigure[] {
  const calm = calmPercent(route.stress_m);
  const heavy = heavyMetres(route.stress_m);
  const path = metres(route.facility_m, "path");
  return [
    { key: "calm", label: "Paths and quiet streets", value: calm === null ? NOT_AVAILABLE : `${calm}%` },
    {
      key: "heavy",
      label: "Heavy traffic",
      value: calm === null ? NOT_AVAILABLE : heavy > 0 ? formatDistance(heavy) : "None",
    },
    { key: "junctions", label: "Stressful junctions", value: junctionFigure(route.intersections) },
    {
      key: "path",
      label: "Off-road path",
      value: route.facility_m === undefined ? NOT_AVAILABLE : path > 0 ? formatDistance(path) : "None",
    },
  ];
}

/** The stress bar's name for a screen reader: each tier's name and its share, in words. */
export function stressBarLabel(segments: ReadonlyArray<{ short: string; percent: number }>): string {
  const parts = segments.filter((s) => s.percent > 0).map((s) => `${s.short} ${s.percent} percent`);
  return `Traffic stress along the route: ${parts.join(", ")}`;
}

/** The same shares as one line of text under the bar, so the bar never relies on colour alone. */
export function stressBarKey(segments: ReadonlyArray<{ short: string; percent: number }>): string {
  return segments
    .filter((s) => s.percent > 0)
    .map((s) => `${s.short} ${s.percent}%`)
    .join(" · ");
}
