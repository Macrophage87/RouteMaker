/**
 * The route panel's facility breakdown: the API's `facility_m`, metres of the
 * route on each of the owner's four classes (src/routemaker/facility.py), in
 * his order - "Off-road bike lanes > Protected Bike Lanes >> Marked Bike Lanes
 * > Ordinary Streets. Sharrows don't count as anything." - plus what no
 * segment rated. Each row has a label and a percentage, never colour alone.
 */
import { wholePercents, type StressMetres } from "./stressBar.ts";

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

export const FACILITY_CLASSES: readonly Omit<FacilityRow, "metres" | "fraction" | "percent">[] = [
  { key: "path", label: "Traffic-free path", hint: "Off-road paths, and roads closed to cars", color: "#1b7f3b" },
  { key: "protected", label: "Protected bike lane", hint: "Separated from traffic by posts, curbs or parking", color: "#2b6cb0" },
  { key: "lane", label: "Painted bike lane", hint: "Marked with paint only", color: "#b7791f" },
  { key: "none", label: "Street, no bike lane", hint: "Sharrows count here", color: "#6b7280" },
  { key: "unknown", label: "Not rated", hint: "No facility rating on these segments", color: "#c4c7cc" },
];

function metresOf(facility: FacilityMetres, key: FacilityKey): number {
  const value = facility[key];
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

/** The rows in the owner's order; empty when nothing was measured (an older API, or all unknown). */
export function facilityRows(facility: FacilityMetres | undefined): FacilityRow[] {
  if (!facility) return [];
  const rows = FACILITY_CLASSES.map((row) => ({ ...row, metres: metresOf(facility, row.key) }));
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
