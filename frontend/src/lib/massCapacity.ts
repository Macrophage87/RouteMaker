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
import { MASS_BANDS, MASS_WIDE_RUN_MI, bandIndex, massBandsAt } from "../massStyle.js";
import type { RouteResponse, StressSpan } from "./api.ts";
import { formatDistance, formatRunMiles, formatSpeedRange } from "./format.ts";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import { wholePercents } from "./stressBar.ts";

/** The ride type this is the capacity map of. */
export const isMassRide = (preset: string | null | undefined): boolean => preset === "mass-ride";

/** The legend's title: the unit and the speed the figure is for (the approved mock-up's). */
export const CAPACITY_SPEED = formatSpeedRange(6, 8);
export const CAPACITY_LEGEND_TITLE = `Riders per minute at ${CAPACITY_SPEED}`;

/**
 * Where the figures come from, as every data source is credited (OWNER-DECISIONS 301, 306): short
 * names here, as the map's own credits.json gives them, and the full reference (the District
 * Department of Transportation's Roadway Block, through DC GIS) in docs/SOURCES.md. In DC the lane, bike-lane and parking widths are the District's
 * own Roadway Block (404: "Absolutely. That's why I focused on DC."), elsewhere OpenStreetMap's lane
 * and width tags. The flow model is the working model (394), from counts of DC Bike Party rides, and
 * is not called calibrated.
 */
export const CAPACITY_SOURCE =
  "An estimate, on the flat, for the narrower direction of the road, less parked cars. Widths in DC: DC Open Data, " +
  "Roadway Block (CC BY 4.0, adapted); elsewhere, and where DC has none: © OpenStreetMap contributors, or a typical " +
  "width for the kind of road. The riders-per-minute model is a working model based on counts of DC Bike Party rides.";

/** The route panel's title for the same figures. */
export const CAPACITY_FIGURE_TITLE = "Riders per minute along the route";

/** The route view's fold for the same figures, in place of "Stress and facilities" (OWNER-DECISIONS 312, 325). */
export const CAPACITY_FOLD_TITLE = "Riders per minute";

/** What the figure is, said once in plain words (the stress legend's LTS_MEANS, for this map). */
export const CAPACITY_MEANS =
  `Riders per minute is how many riders a road lets through each minute on the flat at ${CAPACITY_SPEED}, from the width a ride ` +
  "has in its own direction, after parked cars. " +
  "A ride flows at its narrowest point. Trails, protected bike lanes and bike lanes are not drawn here.";

/** Below the map's first zoom: nothing is drawn yet. */
export const MASS_ZOOM_IN = "Zoom in to see roads and how many riders per minute they carry.";

/**
 * What the Mass Ride map draws at the zoom it is at, below its first zoom only (the bands it shows
 * from there are `massBandsSaid`'s). Null when there is nothing to say.
 */
export function massZoomNotice(zoom: number | null, shown: boolean): string | null {
  if (zoom === null || !shown) return null;
  if (zoom < STRESS_ZOOMS.min) return MASS_ZOOM_IN;
  return null;
}

const bandList = (names: string[]): string =>
  names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

/** The zoom below which the Wide open run applies: the next band's first zoom (422). */
const RUN_BELOW_ZOOM = Math.min(...MASS_BANDS.filter((band) => band.minzoom > MASS_BANDS[MASS_BANDS.length - 1].minzoom).map((b) => b.minzoom));

/**
 * Which bands the Mass Ride map shows at `zoom`, in words (OWNER-DECISIONS 421, 422): "At this zoom
 * the map shows only wide open roads (200 and up riders per minute) ...". The words change only when
 * the set of bands does, so the legend's status line, which says it, is not read again at every zoom
 * step. Null with no zoom yet or the colours switched off.
 */
export function massBandsSaid(zoom: number | null, shown = true): string | null {
  if (zoom === null || !shown || !Number.isFinite(zoom)) return null;
  const at = massBandsAt(zoom) as number[];
  if (at.length === 0) return MASS_ZOOM_IN;
  if (at.length === MASS_BANDS.length) {
    return `At this zoom the map shows every road: ${bandList([...MASS_BANDS].reverse().map((band) => band.name))}.`;
  }
  const shownBands = at.map((i) => MASS_BANDS[i]).reverse();
  const lowest = shownBands[shownBands.length - 1];
  const run =
    Math.floor(zoom) < RUN_BELOW_ZOOM ? `, and only where they run for ${formatRunMiles(MASS_WIDE_RUN_MI)} or more` : "";
  const later = new Map<number, string[]>();
  MASS_BANDS.forEach((band, i) => {
    if (!at.includes(i)) later.set(band.minzoom, [band.name, ...(later.get(band.minzoom) ?? [])]);
  });
  const zoomIn = [...later.entries()]
    .sort(([a], [b]) => a - b)
    .map(([z, names]) => `${bandList(names)} roads from zoom ${z}`);
  return (
    `At this zoom the map shows ${shownBands.length === 1 ? "only " : ""}${bandList(shownBands.map((band) => band.name))} roads ` +
    `(${lowest.min} and up riders per minute)${run}. Zoom in for ${zoomIn.join(", and ")}.`
  );
}

/**
 * What the app-level live region says when the bands change (421): only a change from one set to
 * another (not the first words, when the rider has just come to the Mass Ride map or switched the
 * colours on), and only while the legend, whose own status line says it, is not on screen.
 */
export function massBandsChangeSaid(before: string | null, now: string | null, legendShown: boolean): string | null {
  if (before === null || now === null || before === now || legendShown) return null;
  return now;
}

/** The standing note under the legend: where roads come in, and what this map leaves out (417, 417a, 421, 422). */
export const MASS_ZOOM_HINT =
  `Roads in DC show their riders per minute from zoom ${STRESS_ZOOMS.min}, busy roads included: ` +
  `at zoom 10 and 11 only wide open roads that run ${formatRunMiles(MASS_WIDE_RUN_MI)} or more, at zoom 12 and 13 good roads too, ` +
  "and every road from zoom 14. Stretches marked Avoid show at every zoom. " +
  "Trails, paths, protected bike lanes and bike lanes are not drawn on this map at any zoom, and nor are alleys.";

/** The legend row for a band: "Under 60: bottleneck". */
export function bandLegendText(index: number): string {
  const band = MASS_BANDS[index];
  return `${band.short}: ${band.name}`;
}

/**
 * The one phrase for a stretch marked Avoid, on the map's legend, the route's list, the route line's
 * key and the chart (accessibility review N3). Not "marked by riders": tier-5 Avoid comes from the
 * owner's overrides and corridors today, and riders' reports are not built (325: "If we've marked it avoid").
 */
export const AVOID_LEGEND_TEXT = "Marked Avoid: no capacity given";

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
  /** Where the narrowest section ends. */
  minToM: number | null;
  /** The typical (distance-weighted median) capacity; null with no figures. */
  typicalRpm: number | null;
  /** Metres in each band, lowest first (MASS_BANDS), then the metres marked Avoid and the metres with no figure. */
  bandM: number[];
  avoidM: number;
  unknownM: number;
  /** Metres outside DC, where Mass Ride figures are not supported yet (427): in no band, no figure. */
  outsideM: number;
  /** Whole percents of `totalM`, in the order bands, Avoid, no figure, outside DC; they add up to 100. */
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
  let outsideM = 0;
  let minRpm: number | null = null;
  let minAtM: number | null = null;
  let minToM: number | null = null;
  const weighted: Array<{ rpm: number; m: number }> = [];
  for (const span of spans) {
    const m = Math.max(0, span.to_m - span.from_m);
    if (span.outside_dc) {
      outsideM += m;
      continue;
    }
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
      minToM = span.to_m;
    }
  }
  const totalM = bandM.reduce((a, b) => a + b, 0) + avoidM + unknownM + outsideM;
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
  const parts = [...bandM, avoidM, unknownM, outsideM];
  return { totalM, minRpm, minAtM, minToM, typicalRpm, bandM, avoidM, unknownM, outsideM, percents: wholePercents(parts.map((m) => m / totalM)) };
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

/**
 * The two narrowest points and the two typical figures (OWNER-DECISIONS 424, "Show both."): on the flat,
 * from the route's sections (the width only, as the map is coloured), and with the hills, from the
 * profile (the width and the grade, as the chart draws it). Labelled the same way everywhere they are
 * given: the route view's card, the directions' first sentence, the chart's summary and the capacity fold.
 */
export const NARROWEST_FLAT = "narrowest on the flat";
export const NARROWEST_HILLS = "narrowest with the hills";
export const NARROWEST_BOTH = "narrowest on the flat and with the hills";
export const TYPICAL_FLAT = "typical on the flat";
export const TYPICAL_HILLS = "typical with the hills";
export const TYPICAL_BOTH = "typical on the flat and with the hills";

/** The profile's figures with the hills (the API's `profile.flow`). */
export type HillsFlow = {
  narrowest_riders_per_min: number | null;
  narrowest_m: number | null;
  typical_riders_per_min: number | null;
} | null | undefined;

export interface CapacityPoint {
  rpm: number;
  atM: number;
}

export interface CapacityPair {
  flat: CapacityPoint | null;
  hills: CapacityPoint | null;
  /** The two points are one place: the hills' lies on the flat's narrowest section. */
  samePlace: boolean;
  typicalFlat: number | null;
  typicalHills: number | null;
}

/** How far outside the flat narrowest section the hills' point may lie and still be "the same spot": a profile sample's spacing. */
const SAME_PLACE_M = 30;

export function capacityPair(summary: CapacitySummary | null, flow: HillsFlow): CapacityPair {
  const flat =
    summary && summary.minRpm !== null && summary.minAtM !== null ? { rpm: summary.minRpm, atM: summary.minAtM } : null;
  const hills =
    flow && typeof flow.narrowest_riders_per_min === "number" && typeof flow.narrowest_m === "number"
      ? { rpm: flow.narrowest_riders_per_min, atM: flow.narrowest_m }
      : null;
  const to = summary?.minToM ?? flat?.atM ?? 0;
  const samePlace = !!flat && !!hills && hills.atM >= flat.atM - SAME_PLACE_M && hills.atM <= to + SAME_PLACE_M;
  return {
    flat,
    hills,
    samePlace,
    typicalFlat: summary?.typicalRpm ?? null,
    typicalHills: flow && typeof flow.typical_riders_per_min === "number" ? flow.typical_riders_per_min : null,
  };
}

/** A route's pair: its sections, and its profile where it has one. */
export function routeCapacityPair(route: Partial<Pick<RouteResponse, "stress_spans" | "profile">>): CapacityPair | null {
  const summary = capacitySummary(route.stress_spans);
  if (!summary) return null;
  return capacityPair(summary, route.profile?.flow);
}

/** ", at the start" or ", at 0.2 mi (0.3 km) along". */
const placeText = (m: number): string => (m > 0 ? `, at ${formatDistance(m)} along` : ", at the start");

/** "55 riders per minute (bottleneck)". */
const figure = (rpm: number): string => `${ridersPerMinute(rpm)} (${bandName(rpm)})`;

/** One labelled figure of the pair: the card's term and description, and the words a sentence uses. */
export interface CapacityLine {
  key: string;
  /** "narrowest on the flat"; the card capitalises it. */
  label: string;
  /** "55 riders per minute (bottleneck), at the start". */
  text: string;
}

/**
 * The narrowest point(s) in words: two lines, flat then hills; one where they are the same spot ("say it
 * once"), with both figures where the hills lower it there; one where only one is known.
 */
export function narrowestLines(pair: CapacityPair): CapacityLine[] {
  const { flat, hills } = pair;
  if (flat && hills && pair.samePlace) {
    const figures =
      Math.round(flat.rpm) === Math.round(hills.rpm)
        ? figure(flat.rpm)
        : `${figure(flat.rpm)} on the flat, ${figure(hills.rpm)} with the hills`;
    return [{ key: "narrowest", label: NARROWEST_BOTH, text: `${figures}${placeText(flat.atM)}` }];
  }
  const lines: CapacityLine[] = [];
  if (flat) lines.push({ key: "narrowest-flat", label: NARROWEST_FLAT, text: `${figure(flat.rpm)}${placeText(flat.atM)}` });
  if (hills) lines.push({ key: "narrowest-hills", label: NARROWEST_HILLS, text: `${figure(hills.rpm)}${placeText(hills.atM)}` });
  return lines;
}

/** The typical figure(s), the same way: once where the two agree. */
export function typicalLines(pair: CapacityPair): CapacityLine[] {
  const { typicalFlat: f, typicalHills: hh } = pair;
  if (f !== null && hh !== null && Math.round(f) === Math.round(hh)) return [{ key: "typical", label: TYPICAL_BOTH, text: ridersPerMinute(f) }];
  const lines: CapacityLine[] = [];
  if (f !== null) lines.push({ key: "typical-flat", label: TYPICAL_FLAT, text: ridersPerMinute(f) });
  if (hh !== null) lines.push({ key: "typical-hills", label: TYPICAL_HILLS, text: ridersPerMinute(hh) });
  return lines;
}

/** "Narrowest on the flat": a label at the start of a card's term or a sentence. */
export const capitalise = (label: string): string => label.charAt(0).toUpperCase() + label.slice(1);

/** The narrowest lines as one clause: "narrowest on the flat 55 riders ...; narrowest with the hills 40 riders ...". */
export function narrowestClause(pair: CapacityPair): string {
  const lines = narrowestLines(pair);
  return lines.length === 0 ? "no capacity figure for this route" : lines.map((l) => `${l.label} ${l.text}`).join("; ");
}

/** The route list's row for the parts outside DC (OWNER-DECISIONS 427). */
export const OUTSIDE_DC_ROW = "Outside DC: no figures yet";

/**
 * What the panel and the chart say where part of a Mass Ride is outside the District (427): no
 * greying, the words alone; the narrowest point, the typical figure and the bottlenecks are the DC
 * parts' only. The 418a notice stays as well.
 */
export const OUTSIDE_DC_FIGURES =
  "Mass Ride figures are not supported outside DC yet, so no riders-per-minute figures are given for the parts of this route outside the District.";

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
  rows.push({ key: "avoid", text: AVOID_LEGEND_TEXT, percent: summary.percents[4], metres: summary.avoidM, band: null });
  rows.push({ key: "none", text: "No capacity figure", percent: summary.percents[5], metres: summary.unknownM, band: null });
  rows.push({ key: "outside", text: OUTSIDE_DC_ROW, percent: summary.percents[6], metres: summary.outsideM, band: null });
  return rows.filter((row) => row.metres > 0);
}

/**
 * The route description's lead sentence and the bar's name: the narrowest points, on the flat and with
 * the hills (424; once where they are the same spot), then each band's share.
 */
export function capacityDescription(summary: CapacitySummary, flow?: HillsFlow): string {
  const shares = capacityRows(summary)
    .map((row) => `${row.percent}% ${row.text.toLowerCase()}`)
    .join("; ");
  return `Carrying capacity: ${narrowestClause(capacityPair(summary, flow))}. By distance: ${shares}.`;
}
