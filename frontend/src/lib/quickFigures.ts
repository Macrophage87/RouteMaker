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
import { wholePercents } from "./stressBar.ts";
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

const STRESS_KEYS = ["1", "2", "3", "4", "5", "unknown"] as const;

/**
 * The share of the route (whole percent) on LTS 1 and 2, or null with no stress figures. Rounded as the
 * stress bar's key is (wholePercents, the same keys), so the figure is always that key's LTS 1 plus LTS 2.
 */
export function calmPercent(stress: RouteResponse["stress_m"] | undefined): number | null {
  const each = STRESS_KEYS.map((key) => metres(stress, key));
  const all = each.reduce((sum, m) => sum + m, 0);
  if (!(all > 0)) return null;
  const percents = wholePercents(each.map((m) => m / all));
  return percents[0] + percents[1];
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

/** One share as a screen reader hears it: "LTS 1, comfortable for most people: 61 percent". */
function spokenShare(s: { short: string; label?: string; percent: number }): string {
  const meaning = s.label ? `, ${s.label.charAt(0).toLowerCase()}${s.label.slice(1)}` : "";
  return `${s.short}${meaning}: ${s.percent} percent`;
}

/**
 * The stress bar's name for a screen reader: each tier's name, what it means and its share, in words
 * (the a11y review's S2: "LTS 1 61 percent" was heard as one number). The figure around it is named by
 * its caption, so this does not repeat "Traffic stress along the route".
 */
export function stressBarLabel(segments: ReadonlyArray<{ short: string; label?: string; percent: number }>): string {
  return segments
    .filter((s) => s.percent > 0)
    .map(spokenShare)
    .join("; ");
}

/** The same shares as one line of text under the bar, so the bar never relies on colour alone: "LTS 1: 61%, LTS 2: 30%". */
export function stressBarKey(segments: ReadonlyArray<{ short: string; percent: number }>): string {
  return segments
    .filter((s) => s.percent > 0)
    .map((s) => `${s.short}: ${s.percent}%`)
    .join(", ");
}
