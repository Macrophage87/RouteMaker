/**
 * What a Mass Ride says about carrying capacity, in riders per minute (OWNER-DECISIONS
 * 325-327, 387): the legend's words, the route's narrowest point and the share of its
 * distance in each band, read from the API's coloured sections (`stress_spans[].rpm`).
 *
 * "The focus is on carrying capacity, not LTS here ... Legend, panel and description follow
 * suit: riders per minute in place of the LTS breakdown" (325). The figure is the modelled
 * flow on the flat at 6-8 mph (PLAN.md, "The headline number"); the narrowest point is the
 * route's bottleneck, "a ride flows at its narrowest point". Climbs and signals reduce it
 * further in part 2; this is the figure the map is coloured by.
 *
 * Plain functions of the route, so a test runs them without a map or a browser, and every
 * figure has words (nothing is colour alone).
 */
import { MASS_BANDS, bandIndex } from "../massStyle.js";
import type { RouteResponse, StressSpan } from "./api.ts";
import { formatDistance, formatSpeedRange } from "./format.ts";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import { wholePercents } from "./stressBar.ts";

/** The ride type this is the capacity map of. */
export const isMassRide = (preset: string | null | undefined): boolean => preset === "mass-ride";

/** The legend's title: the unit and the speed the figure is for (the approved mock-up's). */
export const CAPACITY_SPEED = formatSpeedRange(6, 8);
export const CAPACITY_LEGEND_TITLE = `Riders per minute at ${CAPACITY_SPEED}`;

/**
 * Where the figures come from, briefly, as every data source is credited (OWNER-DECISIONS 301, 306): the
 * road widths are OpenStreetMap's lane and width tags, and DC's Roadway Block where it gives the lanes
 * (both credited with the map); the density and pace are calibrated to counts of DC Bike Party rides.
 */
export const CAPACITY_SOURCE =
  "An estimate, on the flat: modelled from OpenStreetMap and DC Roadway Block lane and width data, with a typical width " +
  "for its kind of road where those are not mapped, calibrated to counts of DC Bike Party rides.";

/** The route panel's title for the same figures. */
export const CAPACITY_FIGURE_TITLE = "Riders per minute along the route";

/** The route view's fold for the same figures, in place of "Stress and facilities" (OWNER-DECISIONS 312, 325). */
export const CAPACITY_FOLD_TITLE = "Riders per minute";

/** What the figure is, said once in plain words (the stress legend's LTS_MEANS, for this map). */
export const CAPACITY_MEANS =
  `Riders per minute is how many riders a road lets through each minute on the flat at ${CAPACITY_SPEED}, from its usable width. ` +
  "A ride flows at its narrowest point. Trails and bike lanes are not drawn here.";

/**
 * What the Mass Ride map draws at the zoom it is at, in words (the tiles' levels, core/stress_tiles.py): no
 * roads below z12, the busier (wider) roads from z12, every street from z14. Null when there is nothing to say.
 */
export function massZoomNotice(zoom: number | null, shown: boolean): string | null {
  if (zoom === null || !shown) return null;
  if (zoom < STRESS_ZOOMS.busy) return "Zoom in to see roads and how many riders per minute they carry.";
  if (zoom < STRESS_ZOOMS.quiet) return `Zoom in to see every street. Only the busier roads are drawn until zoom ${STRESS_ZOOMS.quiet}.`;
  return null;
}

/** The standing note under the legend: where roads come in, and what this map leaves out. */
export const MASS_ZOOM_HINT =
  `Roads show from zoom ${STRESS_ZOOMS.busy}: the busier ones first, every street from zoom ${STRESS_ZOOMS.quiet}. ` +
  "Trails, paths and bike lanes are not drawn on this map, and nor are alleys.";

/** The legend row for a band: "Under 60: bottleneck". */
export function bandLegendText(index: number): string {
  const band = MASS_BANDS[index];
  return `${band.short}: ${band.name}`;
}

/** The legend row for a stretch marked Avoid. */
export const AVOID_LEGEND_TEXT = "Avoid (marked by riders): no capacity is given";

/** The word for a figure's band: "bottleneck", "tight", "good" or "wide open"; "" for no figure. */
export function bandName(rpm: number | null | undefined): string {
  const index = bandIndex(rpm ?? null);
  return index === null ? "" : MASS_BANDS[index].name;
}

export interface CapacitySummary {
  /** The distance the sections cover. */
  totalM: number;
  /** The route's narrowest point, riders per minute, and where its section starts. */
  minRpm: number | null;
  minAtM: number | null;
  /** The typical (distance-weighted median) capacity; null with no figures. */
  typicalRpm: number | null;
  /** Metres in each band, lowest first (MASS_BANDS), then the metres marked Avoid and the metres with no figure. */
  bandM: number[];
  avoidM: number;
  unknownM: number;
  /** Whole percents of `totalM`, in the order bands, Avoid, no figure; they add up to 100. */
  percents: number[];
}

/**
 * The route's capacity, from its sections; null where the route is not a Mass Ride's
 * (no section carries a figure: another ride type, an older API, or a table built before
 * the capacity column), so the panel keeps the stress breakdown.
 */
export function capacitySummary(spans: readonly StressSpan[] | null | undefined): CapacitySummary | null {
  if (!spans || spans.length === 0 || !spans.some((s) => typeof s.rpm === "number")) return null;
  const bandM = MASS_BANDS.map(() => 0);
  let avoidM = 0;
  let unknownM = 0;
  let minRpm: number | null = null;
  let minAtM: number | null = null;
  const weighted: Array<{ rpm: number; m: number }> = [];
  for (const span of spans) {
    const m = Math.max(0, span.to_m - span.from_m);
    if (span.tier === 5) {
      avoidM += m;
      continue;
    }
    const index = bandIndex(span.rpm ?? null);
    if (index === null || typeof span.rpm !== "number") {
      unknownM += m;
      continue;
    }
    bandM[index] += m;
    weighted.push({ rpm: span.rpm, m });
    if (minRpm === null || span.rpm < minRpm) {
      minRpm = span.rpm;
      minAtM = span.from_m;
    }
  }
  const totalM = bandM.reduce((a, b) => a + b, 0) + avoidM + unknownM;
  if (!(totalM > 0)) return null;
  weighted.sort((a, b) => a.rpm - b.rpm);
  const counted = weighted.reduce((sum, w) => sum + w.m, 0);
  let typicalRpm: number | null = null;
  let run = 0;
  for (const w of weighted) {
    run += w.m;
    if (run >= counted / 2) {
      typicalRpm = w.rpm;
      break;
    }
  }
  const parts = [...bandM, avoidM, unknownM];
  return { totalM, minRpm, minAtM, typicalRpm, bandM, avoidM, unknownM, percents: wholePercents(parts.map((m) => m / totalM)) };
}

/** The summary of a route, or null (see capacitySummary). */
export function routeCapacity(route: Pick<RouteResponse, "stress_spans">): CapacitySummary | null {
  return capacitySummary(route.stress_spans);
}

/** "55 riders per minute": the unit spelled out, one rider singular. */
export function ridersPerMinute(rpm: number): string {
  return `${Math.round(rpm)} ${Math.round(rpm) === 1 ? "rider" : "riders"} per minute`;
}

/** The narrowest point in words: "55 riders per minute (bottleneck), at 0.2 mi (0.3 km)". */
export function narrowestText(summary: CapacitySummary): string {
  if (summary.minRpm === null) return "No capacity figure for this route";
  const at = summary.minAtM !== null && summary.minAtM > 0 ? `, at ${formatDistance(summary.minAtM)} along` : ", at the start";
  return `${ridersPerMinute(summary.minRpm)} (${bandName(summary.minRpm)})${at}`;
}

/** One band's row in the route's list: its name, share and length. */
export interface CapacityRow {
  key: string;
  /** "Under 60: bottleneck". */
  text: string;
  percent: number;
  metres: number;
  /** The band index (0-3), or null for the Avoid and no-figure rows. */
  band: number | null;
}

/** The rows of the route's list, bands lowest first, then Avoid and "No figure" where there are any; empty rows left out. */
export function capacityRows(summary: CapacitySummary): CapacityRow[] {
  const rows: CapacityRow[] = MASS_BANDS.map((band: (typeof MASS_BANDS)[number], i: number) => ({
    key: band.key,
    text: bandLegendText(i),
    percent: summary.percents[i],
    metres: summary.bandM[i],
    band: i,
  }));
  rows.push({ key: "avoid", text: "Avoid: no capacity given", percent: summary.percents[4], metres: summary.avoidM, band: null });
  rows.push({ key: "none", text: "No capacity figure", percent: summary.percents[5], metres: summary.unknownM, band: null });
  return rows.filter((row) => row.metres > 0);
}

/** The route description's lead sentence and the bar's name: the narrowest point, then each band's share. */
export function capacityDescription(summary: CapacitySummary): string {
  const shares = capacityRows(summary)
    .map((row) => `${row.percent}% ${row.text.toLowerCase()}`)
    .join("; ");
  return `Carrying capacity: narrowest point ${narrowestText(summary)}. By distance: ${shares}.`;
}
