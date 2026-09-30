/**
 * The route panel's stress breakdown: the API's `stress_m` (metres of the route
 * on each tier, plus what no segment rated) as bar segments. Colours are the
 * overlay's own, and every segment carries a label and a percentage so the bar
 * does not rely on colour alone.
 */
import { STRESS_TIERS } from "../stressStyle.js";

export type StressKey = "1" | "2" | "3" | "4" | "5" | "unknown";
export type StressMetres = Partial<Record<StressKey, number>>;

export interface StressSegment {
  key: StressKey;
  short: string;
  label: string;
  color: string;
  metres: number;
  fraction: number;
  /** Whole percent; the segments' percents always add up to 100. */
  percent: number;
}

/** What no segment rated: the breakdown's and the route line's colour for it. */
export const UNRATED = { short: "Not rated", label: "No stress rating on these segments", color: "#9aa0a6" };
const UNKNOWN = UNRATED;

function metresOf(stress: StressMetres, key: StressKey): number {
  const value = stress[key];
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

/** Largest-remainder rounding, so the labels never add up to 99 or 101. */
export function wholePercents(fractions: number[]): number[] {
  const raw = fractions.map((f) => f * 100);
  const floors = raw.map(Math.floor);
  let short = 100 - floors.reduce((a, b) => a + b, 0);
  const order = raw
    .map((value, index) => ({ index, remainder: value - Math.floor(value) }))
    .sort((a, b) => b.remainder - a.remainder || a.index - b.index);
  for (const { index } of order) {
    if (short <= 0) break;
    floors[index] += 1;
    short -= 1;
  }
  return floors;
}

export function stressSegments(stress: StressMetres): StressSegment[] {
  const rows = [
    ...STRESS_TIERS.map((t) => ({
      key: String(t.tier) as StressKey,
      short: t.short,
      label: t.label,
      color: t.color,
    })),
    { key: "unknown" as StressKey, ...UNKNOWN },
  ].map((row) => ({ ...row, metres: metresOf(stress, row.key) }));
  const total = rows.reduce((sum, row) => sum + row.metres, 0);
  if (!(total > 0)) return [];
  const fractions = rows.map((row) => row.metres / total);
  const percents = wholePercents(fractions);
  return rows.map((row, i) => ({ ...row, fraction: fractions[i], percent: percents[i] }));
}
