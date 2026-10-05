/**
 * The route panel's stress breakdown: the API's `stress_m` (metres of the route
 * on each tier, plus what no segment rated) as bar segments. Colours are the
 * overlay's own, and every segment carries a label and a percentage so the bar
 * does not rely on colour alone. Avoid is the route's own magenta, as on the route
 * line and the route chart (OWNER-DECISIONS 397), with its cross-hatch in the
 * near-black the route chart's strip uses (styles.css .stress-seg-5): this bar shows
 * the route, beside its line, so one Avoid stretch has one colour (r3 spec, SF-1).
 */
import { ACCESSIBILITY_PALETTE, currentPalette, currentTiers } from "../stressStyle.js";
import { ROUTE_AVOID_HALO, ROUTE_AVOID_MAGENTA } from "./avoidColour.ts";

export type StressKey = "1" | "2" | "3" | "4" | "5" | "unknown";
export type StressMetres = Partial<Record<StressKey, number>>;

export interface StressSegment {
  key: StressKey;
  short: string;
  label: string;
  color: string;
  /** The tier's casing colour, or the colour itself for a row with none: the accent of the segment's pattern (styles.css, .stress-seg-5). */
  casing: string;
  metres: number;
  fraction: number;
  /** Whole percent; the segments' percents always add up to 100. */
  percent: number;
}

/** What no segment rated: the breakdown's and the route line's colour for it. */
export const UNRATED = { short: "Not rated", label: "No stress rating on these segments", color: "#9aa0a6" };

/**
 * "Not rated" in the colour-blind-friendly palette: a warm grey of the same
 * lightness. The cool grey is only 16 to 19 CIEDE2000 from that palette's LTS 1
 * and LTS 2 blues under some simulated colour visions (review r1, accessibility);
 * this one is at least 24 from every tier and from the traffic-free violet,
 * under every vision (stressContrast.test.ts).
 */
export const UNRATED_CVD_COLOUR = "#9f9c93";

/** What no segment rated, in the palette in use. */
export function unrated(palette: string = currentPalette()): typeof UNRATED {
  return palette === ACCESSIBILITY_PALETTE ? { ...UNRATED, color: UNRATED_CVD_COLOUR } : UNRATED;
}

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
    ...currentTiers().map((t: { tier: number; short: string; label: string; color: string; casing: string }) => ({
      key: String(t.tier) as StressKey,
      short: t.short,
      label: t.label,
      ...(t.tier === 5 ? { color: ROUTE_AVOID_MAGENTA, casing: ROUTE_AVOID_HALO } : { color: t.color, casing: t.casing }),
    })),
    { key: "unknown" as StressKey, ...unrated(), casing: unrated().color },
  ].map((row) => ({ ...row, metres: metresOf(stress, row.key) }));
  const total = rows.reduce((sum, row) => sum + row.metres, 0);
  if (!(total > 0)) return [];
  const fractions = rows.map((row) => row.metres / total);
  const percents = wholePercents(fractions);
  return rows.map((row, i) => ({ ...row, fraction: fractions[i], percent: percents[i] }));
}
