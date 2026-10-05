/**
 * The route panel's facility breakdown: the API's `facility_m`, metres of the
 * route on each of the owner's four classes (src/routemaker/facility.py), in
 * his order - "Off-road bike lanes > Protected Bike Lanes >> Marked Bike Lanes
 * > Ordinary Streets. Sharrows don't count as anything." - plus what no
 * segment rated. Each row has a label and a percentage, never colour alone.
 */
import { wholePercents, type StressMetres } from "./stressBar.ts";
import type { StressSpan } from "./api.ts";
import { FACILITIES, HIGH_STRESS_LANE_MIN_TIER } from "../stressStyle.js";

export type FacilityKey = "path" | "protected" | "lane" | "none" | "unknown";
export type FacilityMetres = Partial<Record<FacilityKey, number>>;

export interface FacilityRow {
  key: FacilityKey;
  label: string;
  hint: string;
  color: string;
  metres: number;
  fraction: number;
  percent: number;
}

/** A rail's colour on the map (stressStyle.js, FACILITIES): the bar and its swatches use the same, so they match the rails. */
function railColour(facility: string): string {
  return (FACILITIES.find((f: { facility: string }) => f.facility === facility) as { color: string }).color;
}

export const FACILITY_CLASSES: readonly Omit<FacilityRow, "metres" | "fraction" | "percent">[] = [
  { key: "path", label: "Traffic-free path", hint: "Off-road paths, and roads closed to cars", color: railColour("path") },
  { key: "protected", label: "Protected bike lane", hint: "Separated from traffic by posts, curbs or parking", color: railColour("protected") },
  { key: "lane", label: "Painted lane (no separation)", hint: "Marked with paint only", color: railColour("lane") },
  { key: "none", label: "Street, no bike lane", hint: "Sharrows count here", color: "#6b7280" },
  { key: "unknown", label: "Not rated", hint: "No facility rating on these segments", color: "#c4c7cc" },
];

function metresOf(facility: FacilityMetres, key: FacilityKey): number {
  const value = facility[key];
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

/**
 * Metres of painted lane on LTS 4 and Avoid, from the route's stress spans
 * (OWNER-DECISIONS 275): the stretches the map does not draw a lane on unless
 * the rider asks. Zero without spans (an older API).
 */
export function highStressLaneMetres(spans: readonly Pick<StressSpan, "from_m" | "to_m" | "tier" | "facility">[] | undefined): number {
  let metres = 0;
  for (const span of spans ?? []) {
    if (span.facility === "lane" && typeof span.tier === "number" && span.tier >= HIGH_STRESS_LANE_MIN_TIER && span.to_m > span.from_m) {
      metres += span.to_m - span.from_m;
    }
  }
  return metres;
}

/**
 * The facility totals with painted lanes on LTS 4 and Avoid counted as "no
 * facility" (OWNER-DECISIONS 275), unless `showHighStressLanes`. Never takes
 * more than the route has of painted lane.
 */
export function facilityMetresShown(
  facility: FacilityMetres | undefined,
  spans: readonly Pick<StressSpan, "from_m" | "to_m" | "tier" | "facility">[] | undefined,
  showHighStressLanes: boolean,
): FacilityMetres | undefined {
  if (!facility || showHighStressLanes) return facility;
  const lane = metresOf(facility, "lane");
  const moved = Math.min(highStressLaneMetres(spans), lane);
  if (!(moved > 0)) return facility;
  return { ...facility, lane: lane - moved, none: metresOf(facility, "none") + moved };
}

/**
 * The rows in the owner's order; empty when nothing was measured (an older
 * API, or all unknown). With the route's `spans`, painted lane on LTS 4 and
 * Avoid counts as no facility unless `showHighStressLanes`.
 */
export function facilityRows(
  facility: FacilityMetres | undefined,
  spans?: readonly Pick<StressSpan, "from_m" | "to_m" | "tier" | "facility">[],
  showHighStressLanes = false,
): FacilityRow[] {
  const shown = facilityMetresShown(facility, spans, showHighStressLanes);
  if (!shown) return [];
  const rows = FACILITY_CLASSES.map((row) => ({ ...row, metres: metresOf(shown, row.key) }));
  const total = rows.reduce((sum, row) => sum + row.metres, 0);
  const rated = total - rows[rows.length - 1].metres;
  if (!(total > 0) || !(rated > 0)) return [];
  const fractions = rows.map((row) => row.metres / total);
  const percents = wholePercents(fractions);
  return rows.map((row, i) => ({ ...row, fraction: fractions[i], percent: percents[i] }));
}

/** Metres of the route on "legal but avoid" (stress tier 5); 0 from an older API. */
export function avoidMetres(stress: StressMetres | undefined): number {
  const value = stress?.["5"];
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

/** Which half of the route summary's facility breakdown a FacilityBreakdown draws (OWNER-DECISIONS 312). */
export type BreakdownPart = "all" | "notices" | "figures";

/**
 * The split: the notices (the traffic-tolerant warning, the roads best avoided, what the hills search
 * found) stay in view, and the figures (the route colors and the bike facilities) go in the "Stress and
 * facilities" fold; "all" is both, once each.
 */
export function breakdownParts(part: BreakdownPart): { notices: boolean; figures: boolean } {
  return { notices: part !== "figures", figures: part !== "notices" };
}
