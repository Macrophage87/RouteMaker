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
import { formatDistance, formatDuration } from "./format.ts";
import { t } from "./i18n.ts";
import { junctionCounts } from "./intersectionMarkers.ts";
import { wholePercents } from "./stressBar.ts";
import type { RouteResponse } from "./api.ts";

/** The turns the directions give (left, right, bear and U-turns; not "continue" or straight on at a junction). */
export function turnTotal(route: Pick<RouteResponse, "description">): number {
  const turning = new Set(["left", "right", "bear_left", "bear_right", "uturn"]);
  return (route.description ?? []).filter((entry) => entry.kind === "stretch" && turning.has(entry.turn?.movement ?? "")).length;
}

/**
 * Group Ride's line under the stress bar (the 2026-10-28 audit, P6; the ride type plans for quiet roads and fewer
 * turns): "Quiet roads · 4 turns"; "85% quiet roads · 4 turns" where under 90% of it is LTS 1 or 2. The bar keeps
 * each share in its name.
 */
export function groupRideLine(route: Pick<RouteResponse, "description" | "stress_m">): string {
  const calm = calmPercent(route.stress_m);
  const turns = turnTotal(route);
  const quiet = calm === null ? null : calm >= 90 ? t("Quiet roads") : t("{percent}% quiet roads", { percent: calm });
  const turnWords = turns === 1 ? t("1 turn") : t("{count} turns", { count: turns });
  return quiet ? `${quiet} · ${turnWords}` : turnWords;
}

export interface QuickFigure {
  key: "calm" | "heavy" | "junctions" | "path" | "turns" | "waits" | "surface";
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

/**
 * The metres on unpaved sections (`stress_spans`' `unpaved`, OWNER-DECISIONS 302), gravel and rough alike; null where
 * the planner sent no sections (an older API), so "none" is never guessed.
 */
export function unpavedMetres(spans: RouteResponse["stress_spans"] | undefined): number | null {
  if (!spans) return null;
  return spans.reduce((sum, span) => sum + (span.unpaved === true ? Math.max(0, span.to_m - span.from_m) : 0), 0);
}

/** Under this (metres, 0.05 mi) unpaved is not said: a few metres where a route crosses a gravel lot. */
export const UNPAVED_SAID_M = 80;

/**
 * The route's distance by surface, from its sections (`stress_spans`): paved, gravel (unpaved, not rough: the map's
 * grey), dirt (rough: dirt, grass, a rutted track; the map's brown), unpaved of a kind not said, and not known (no
 * surface tag; the map draws it as paved). Null where the planner sent no sections (an older API).
 */
export interface SurfaceMetres {
  paved: number;
  gravel: number;
  dirt: number;
  unpaved: number;
  unknown: number;
}

export function surfaceMetres(spans: RouteResponse["stress_spans"] | undefined): SurfaceMetres | null {
  if (!spans) return null;
  const out: SurfaceMetres = { paved: 0, gravel: 0, dirt: 0, unpaved: 0, unknown: 0 };
  for (const span of spans) {
    const m = Math.max(0, span.to_m - span.from_m);
    if (span.unpaved === true) {
      if (span.rough === false) out.gravel += m;
      else if (span.rough === true) out.dirt += m;
      else out.unpaved += m;
    } else if (span.unpaved === false) out.paved += m;
    else out.unknown += m;
  }
  return out;
}

/**
 * Surface at a glance (backlog 2026-11-12, Plan item 10): the unpaved riding by kind, for the line under the stress bar
 * in Go and Plan: ["1.2 mi (1.9 km) gravel", "0.3 mi (0.5 km) dirt"]. Empty where the route rides under
 * UNPAVED_SAID_M unpaved, so a paved route's line stays as it was.
 */
export function surfaceGlanceParts(spans: RouteResponse["stress_spans"] | undefined): string[] {
  const s = surfaceMetres(spans);
  if (!s || s.gravel + s.dirt + s.unpaved < UNPAVED_SAID_M) return [];
  return [
    s.gravel >= PLAIN_MIN_M ? t("{distance} gravel", { distance: formatDistance(s.gravel) }) : null,
    s.dirt >= PLAIN_MIN_M ? t("{distance} dirt", { distance: formatDistance(s.dirt) }) : null,
    s.unpaved >= PLAIN_MIN_M ? t("{distance} unpaved", { distance: formatDistance(s.unpaved) }) : null,
  ].filter((part): part is string => part !== null);
}

/** A surface is said in the Surface figure from this share of the route (not known: untagged streets are common). */
export const SURFACE_UNKNOWN_SAID = 0.1;

/**
 * Plan's Surface figure (English, as Plan is): "All paved", or "12.1 mi (19.5 km) paved, 1.2 mi (1.9 km) gravel, 0.3 mi
 * (0.5 km) dirt", with "; 2.0 mi (3.2 km) not known" where a tenth or more of the route has no surface tag. Untagged
 * sections count as paved below that, as the map draws them; unpaved under UNPAVED_SAID_M is not said.
 */
export function surfaceFigure(spans: RouteResponse["stress_spans"] | undefined): string {
  const s = surfaceMetres(spans);
  if (!s) return NOT_AVAILABLE;
  const all = s.paved + s.gravel + s.dirt + s.unpaved + s.unknown;
  if (!(all > 0)) return NOT_AVAILABLE;
  const rough = s.gravel + s.dirt + s.unpaved;
  const sayUnknown = s.unknown >= PLAIN_MIN_M && s.unknown / all >= SURFACE_UNKNOWN_SAID;
  const unpavedSaid = rough >= UNPAVED_SAID_M;
  const paved = s.paved + (sayUnknown ? 0 : s.unknown) + (unpavedSaid ? 0 : rough);
  const tail = sayUnknown ? `; ${formatDistance(s.unknown)} not known` : "";
  if (!unpavedSaid) {
    if (!sayUnknown) return "All paved";
    return paved >= PLAIN_MIN_M ? `${formatDistance(paved)} paved${tail}` : `${formatDistance(s.unknown)} not known`;
  }
  const parts = [
    paved >= PLAIN_MIN_M ? `${formatDistance(paved)} paved` : null,
    s.gravel >= PLAIN_MIN_M ? `${formatDistance(s.gravel)} gravel` : null,
    s.dirt >= PLAIN_MIN_M ? `${formatDistance(s.dirt)} dirt` : null,
    s.unpaved >= PLAIN_MIN_M ? `${formatDistance(s.unpaved)} unpaved` : null,
  ].filter((part): part is string => part !== null);
  return parts.length ? parts.join(", ") + tail : tail.slice(2);
}

/** "4 min", "Under 1 min" or "None": the time the route waits at signals and stop signs (`junction_delay_s`, inside the moving time). */
export function waitFigure(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return NOT_AVAILABLE;
  if (seconds <= 0) return "None";
  return seconds < 30 ? "Under 1 min" : formatDuration(seconds);
}

/**
 * The quick figures (OWNER-DECISIONS 312's four), then the route's turn burden (owner decision 254, the backlog's
 * "fewer turns" item, 2026-11-12): its turns and the time it waits at lights and stops, so two routes that differ mainly
 * in fiddliness no longer read the same; then its surface (Plan item 10).
 */
export function quickFigures(
  route: Pick<RouteResponse, "stress_m" | "facility_m" | "intersections"> &
    Partial<Pick<RouteResponse, "description" | "junction_delay_s" | "stress_spans">>,
): QuickFigure[] {
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
    { key: "turns", label: "Turns", value: route.description == null ? NOT_AVAILABLE : turnTotal(route) > 0 ? String(turnTotal(route)) : "None" },
    { key: "waits", label: "Waiting at lights and stops", value: waitFigure(route.junction_delay_s) },
    // Every route's surface (backlog 2026-11-12, Plan item 10: "Is this OK on my road bike?"), by kind where it has
    // unpaved riding; one line, "All paved" on most routes.
    ...(route.stress_spans?.length ? [{ key: "surface" as const, label: "Surface", value: surfaceFigure(route.stress_spans) }] : []),
  ];
}

/** One share as a screen reader hears it: "LTS 1, comfortable for most people: 61 percent". */
/** A tier's meaning where its own label would read badly after its name ("Avoid, legal, but best avoided"). */
const SPOKEN_MEANING: Record<string, string> = { "5": "roads best avoided" };

function spokenShare(s: { key?: string; short: string; label?: string; percent: number }): string {
  const own = s.key !== undefined ? SPOKEN_MEANING[s.key] : undefined;
  const meaning = own ? `, ${own}` : s.label ? `, ${s.label.charAt(0).toLowerCase()}${s.label.slice(1)}` : "";
  return `${s.short}${meaning}: ${s.percent} percent`;
}

/**
 * The stress bar's name for a screen reader: each tier's name, what it means and its share, in words
 * (the a11y review's S2: "LTS 1 61 percent" was heard as one number). The figure around it is named by
 * its caption, so this does not repeat "Traffic stress along the route".
 */
export function stressBarLabel(segments: ReadonlyArray<{ key?: string; short: string; label?: string; percent: number }>): string {
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

/**
 * The metres on busy roads: LTS 3 and 4, and roads marked legal but best avoided ("busy roads (LTS 3-4)", as the
 * detour notice and the Traffic help say it).
 */
export function busyMetres(stress: RouteResponse["stress_m"] | undefined): number {
  return metres(stress, "3") + heavyMetres(stress);
}

/** Less than this of a part is not said (a few metres where a route meets a road). */
export const PLAIN_MIN_M = 10;
/** The calm share (calmPercent) at and above which a route is "Mostly calm", and "Some busy roads". */
export const MOSTLY_CALM_PERCENT = 75;
export const SOME_BUSY_PERCENT = 40;

/** How calm the route is in two or three words: "All calm", "Mostly calm", "Some busy roads" or "Mostly busy"; null with no stress figures. */
export function calmWords(stress: RouteResponse["stress_m"] | undefined): string | null {
  const calm = calmPercent(stress);
  if (calm === null) return null;
  if (busyMetres(stress) < PLAIN_MIN_M) return t("All calm");
  return calm >= MOSTLY_CALM_PERCENT ? t("Mostly calm") : calm >= SOME_BUSY_PERCENT ? t("Some busy roads") : t("Mostly busy");
}

/** "1.1 mi (1.8 km) on paths and protected lanes", "… on paths", "… on protected lanes"; null with neither. */
export function calmWaysText(facility: RouteResponse["facility_m"] | undefined): string | null {
  const path = metres(facility, "path");
  const lane = metres(facility, "protected");
  if (path + lane < PLAIN_MIN_M) return null;
  const distance = formatDistance(path + lane);
  if (path >= PLAIN_MIN_M && lane >= PLAIN_MIN_M) return t("{distance} on paths and protected lanes", { distance });
  return path >= lane ? t("{distance} on paths", { distance }) : t("{distance} on protected lanes", { distance });
}

/**
 * Go's line under the stress bar (the owner's P1, 2026-10-28), in place of the shares ("LTS 1: 75%, LTS 4: 21%"):
 * "Mostly calm · 1.1 mi (1.8 km) on paths and protected lanes · busy road for 0.2 mi (0.3 km)", each part left out
 * where it is nothing, then its unpaved riding by kind where it has some (surfaceGlanceParts: "1.2 mi gravel"). Its
 * parts, shown joined by " · " and said joined by commas; the shares stay the bar's name for
 * a screen reader (stressBarLabel).
 */
export function stressPlainParts(route: Pick<RouteResponse, "stress_m" | "facility_m"> & Partial<Pick<RouteResponse, "stress_spans">>): string[] {
  const busy = busyMetres(route.stress_m);
  return [
    calmWords(route.stress_m),
    calmWaysText(route.facility_m),
    busy >= PLAIN_MIN_M ? t("busy road for {distance}", { distance: formatDistance(busy) }) : null,
    ...surfaceGlanceParts(route.stress_spans),
  ].filter((part): part is string => part !== null);
}

/** The shares of the route on a traffic-free path and on a protected lane (lib/facilityBar.ts facilityRows), for Go's strip. */
export function calmWayShares(rows: ReadonlyArray<{ key: string; metres: number; fraction: number; percent: number }>): CalmWayShare[] {
  return rows
    .filter((row): row is CalmWayShare => (row.key === "path" || row.key === "protected") && row.metres >= PLAIN_MIN_M)
    .map(({ key, metres, fraction, percent }) => ({ key, metres, fraction, percent }));
}

/** One row of the strip under Go's stress bar: a traffic-free path or a protected lane, its share of the route. */
export interface CalmWayShare {
  key: "path" | "protected";
  metres: number;
  fraction: number;
  percent: number;
}

/** The strip's name for a screen reader: "Traffic-free paths: 0.8 mi (1.3 km), 61 percent; protected bike lanes: …". */
export function calmWaysLabel(rows: readonly CalmWayShare[]): string {
  return rows
    .filter((row) => row.metres >= PLAIN_MIN_M)
    .map((row) =>
      row.key === "path"
        ? t("Traffic-free paths: {distance}, {percent} percent", { distance: formatDistance(row.metres), percent: row.percent })
        : t("Protected bike lanes: {distance}, {percent} percent", { distance: formatDistance(row.metres), percent: row.percent }),
    )
    .join("; ");
}
