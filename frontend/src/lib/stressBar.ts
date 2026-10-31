/**
 * The route panel's stress breakdown: the API's `stress_m` (metres of the route
 * on each tier, plus what no segment rated) as bar segments. Colours are the
 * overlay's own, and every segment carries a label and a percentage so the bar
 * does not rely on colour alone. Avoid is the route's own magenta, as on the route
 * line and the route chart (OWNER-DECISIONS 397), with its cross-hatch in the
 * near-black the route chart's strip uses (styles.css .stress-seg-5): this bar shows
 * the route, beside its line, so one Avoid stretch has one colour (r3 spec, SF-1).
 * The magenta is only for a route that uses Avoid ("Only do if a route uses it"): the
 * fold's list shows every tier, so a route with no Avoid lists "Avoid 0%" in the
 * palette's own Avoid colour, not the magenta (r4 spec, S-SF1).
 *
 * Half steps (the owner, 2026-10-31: "The bar under a route, the ride summary and post pages get the half-step
 * colours, so a 3.5 stretch is orange there too"): where the route's sections (`stress_spans`) can be read, the bar
 * is built from them, each half step ridden in a segment of its own after its lower level, in the colour the route
 * line draws it (routeColours.ts, from the same stressStyle.js halfStep). In the colour-blind-friendly palette, where
 * a half step is its lower level's colour with the next level's dash (HALF_DASHED), the segment carries that dash
 * (`dash`, styles.css .stress-seg-dashed). A half step that is not ridden is not listed.
 */
import { ACCESSIBILITY_PALETTE, currentPalette, currentTiers, halfStep } from "../stressStyle.js";
import type { StressSpan } from "./api.ts";
import { ROUTE_AVOID_HALO, ROUTE_AVOID_MAGENTA } from "./avoidColour.ts";
import { STEP_WORDS } from "./stepWords.ts";

export type StressKey = "1" | "2" | "3" | "4" | "5" | "unknown";
export type StressMetres = Partial<Record<StressKey, number>>;
/** A half step's key (routeColours.ts HalfClassKey): its lower level and "h". */
export type HalfKey = "1h" | "2h" | "3h" | "4h";
/** The bar's keys: the whole levels, the half steps and what no segment rated. */
export type BarKey = StressKey | HalfKey;
export type BarMetres = Partial<Record<BarKey, number>>;
/** What the bar reads of a route section. */
export type BarSpan = Pick<StressSpan, "from_m" | "to_m" | "tier"> & Partial<Pick<StressSpan, "half">>;

export interface StressSegment {
  key: BarKey;
  short: string;
  label: string;
  color: string;
  /** The tier's casing colour, or the colour itself for a row with none: the accent of the segment's pattern (styles.css, .stress-seg-5). */
  casing: string;
  metres: number;
  fraction: number;
  /** Whole percent; the segments' percents always add up to 100. */
  percent: number;
  /** A half step's dash, in the next level's colour, where it has no colour of its own (the colour-blind-friendly palette). */
  dash?: string;
  /** The outline under that dash where the dash is too close to the segment's colour (stressStyle.js HALF_OUTLINES). */
  dashOutline?: string;
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

function metresOf(stress: BarMetres, key: BarKey): number {
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

/**
 * The metres on each level from the route's sections, a half step (`half: true`) under its own key, or null where
 * there are none to read (an older API, or an answer kept without them). A section with no tier is unrated.
 */
export function spanMetres(spans: readonly BarSpan[] | null | undefined): BarMetres | null {
  if (!spans || spans.length === 0) return null;
  const out: BarMetres = {};
  for (const span of spans) {
    const length = span.to_m - span.from_m;
    if (!(Number.isFinite(length) && length > 0)) continue;
    const tier = span.tier;
    const key: BarKey =
      tier === null || !Number.isInteger(tier) || tier < 1 || tier > 5
        ? "unknown"
        : span.half === true && tier < 5
          ? (`${tier}h` as HalfKey)
          : (String(tier) as StressKey);
    out[key] = (out[key] ?? 0) + length;
  }
  return Object.keys(out).length > 0 ? out : null;
}

type Tier = { tier: number; short: string; label: string; color: string; casing: string };

/** A half step's row, in the colour the route line gives it (routeColours.ts routeClasses, from the same halfStep). */
function halfRow(tier: Tier, tiers: Tier[]) {
  // Never null: every level below Avoid has a step above it.
  const half = halfStep(tier.tier, tiers)!;
  const step = String(tier.tier + 0.5);
  return {
    key: `${tier.tier}h` as HalfKey,
    short: `LTS ${step}`,
    label: STEP_WORDS[step],
    color: (half.solid ? half.color : tier.color) as string,
    casing: (half.solid ? half.outline : tier.casing) as string,
    ...(half.solid ? {} : { dash: half.color as string, ...(half.outline ? { dashOutline: half.outline as string } : {}) }),
  };
}

/**
 * The bar's segments: every whole level (an empty one at 0%), each half step ridden after its lower level, then what
 * no segment rated. From the route's sections where given (`spans`, so the bar matches the route line, which is drawn
 * from them), else from the whole-level totals (`stress`).
 */
export function stressSegments(stress: BarMetres, spans?: readonly BarSpan[] | null): StressSegment[] {
  const metres = spanMetres(spans) ?? stress;
  const usesAvoid = metresOf(metres, "5") > 0;
  const tiers: Tier[] = currentTiers();
  const rows = [
    ...tiers.flatMap((t) => [
      {
        key: String(t.tier) as BarKey,
        short: t.short,
        label: t.label,
        ...(t.tier === 5 && usesAvoid ? { color: ROUTE_AVOID_MAGENTA, casing: ROUTE_AVOID_HALO } : { color: t.color, casing: t.casing }),
      },
      ...(t.tier < 5 && metresOf(metres, `${t.tier}h` as HalfKey) > 0 ? [halfRow(t, tiers)] : []),
    ]),
    { key: "unknown" as BarKey, ...unrated(), casing: unrated().color },
  ].map((row) => ({ ...row, metres: metresOf(metres, row.key) }));
  const total = rows.reduce((sum, row) => sum + row.metres, 0);
  if (!(total > 0)) return [];
  const fractions = rows.map((row) => row.metres / total);
  const percents = wholePercents(fractions);
  return rows.map((row, i) => ({ ...row, fraction: fractions[i], percent: percents[i] }));
}

/** A segment's classes: its level's pattern (a half step's is its lower level's, styles.css), and the dash where it has one. */
export function segmentClass(s: Pick<StressSegment, "key" | "dash">): string {
  return `stress-seg-${s.key}${s.dash ? " stress-seg-dashed" : ""}`;
}

/** A segment's colours as a style: its fill, its pattern's accent, and its dash and the dash's outline where it has them. */
export function segmentStyle(s: Pick<StressSegment, "color" | "casing" | "dash" | "dashOutline">): Record<string, string> {
  return {
    backgroundColor: s.color,
    "--seg-accent": s.casing,
    ...(s.dash ? { "--seg-dash": s.dash } : {}),
    ...(s.dashOutline ? { "--seg-dash-outline": s.dashOutline } : {}),
  };
}
