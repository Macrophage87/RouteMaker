/**
 * The hover card of an interval stretch (the owner, 2026-11-18: "Allow a mouseover with elevation profile as well, it
 * should also give distance and a rough estimate of interval time", and "Mark bollards on the interval card and have
 * it noted"): as a climb's (lib/featureHover.ts), a small card at the mouse with the stretch's name, its length, rise,
 * the minutes it takes at the build's 18 mph (slowed on a climb), which way it holds and any bollards on it; then its
 * elevation profile (GET /api/intervals/{id}/profile, the router's USGS 3DEP heights, start to end), once the mouse
 * has rested on it. Mouse only, as the climbs' hover; nothing here changes a route.
 */
import { createElement as h, type ReactElement } from "react";
import { ElevationProfileChart, profileEnds, type ChartProfile } from "./climbCard.ts";
import { KMH_PER_MPH, formatClimb, formatDistance, formatSpeed, unitsFirstDeep } from "./format.ts";
import type { LonLat } from "./geo.ts";
import type { HoverWords } from "./featureHover.ts";
import { t } from "./i18n.ts";
import { INTERVALS_LINE_LAYER } from "./intervals.ts";

export const INTERVAL_TITLE = t("Interval stretch");
/** The pace the stretch file times a stretch at (src/pipeline/interval_layer.py, 18 mph). */
const BUILD_KMH = 18 * KMH_PER_MPH;

/** The words from a drawn stretch's properties (lib/intervals.ts intervalsGeoJson). */
export function intervalHoverWords(p: Record<string, unknown>): HoverWords {
  const name = typeof p.n === "string" && p.n ? p.n : null;
  const lengthM = Number(p.l) || 0;
  const riseM = Number(p.r) || 0;
  const minutes = Number(p.t) || 0;
  const bollards = Number(p.k) || 0;
  const one = p.one === true;
  const grade = lengthM > 0 ? (riseM / lengthM) * 100 : 0;
  const parts = [
    formatDistance(lengthM),
    riseM >= 1 ? t("rises {climb} at {grade}%", { climb: formatClimb(riseM), grade: grade.toFixed(1) }) : t("flat"),
    t("about {minutes} min at {speed}", { minutes: minutes.toFixed(1), speed: formatSpeed(BUILD_KMH) }),
    one ? t("this way only (the arrows)") : t("either way"),
  ];
  if (bollards > 0) parts.push(bollards === 1 ? t("1 bollard to ride through") : t("{count} bollards to ride through", { count: bollards }));
  return { key: `interval|${String(p.id)}`, title: name ?? INTERVAL_TITLE, detail: parts.join(", ") };
}

/** GET /api/intervals/{id}/profile (core.api.IntervalProfileOut). */
export interface IntervalProfile extends ChartProfile {
  id: string;
  max_grade_pct: number | null;
}

export function intervalProfileUrl(id: string): string {
  return `/api/intervals/${encodeURIComponent(id)}/profile`;
}

function looksLikeProfile(body: unknown): body is IntervalProfile {
  const b = body as Partial<IntervalProfile> | null;
  return !!b && Array.isArray(b.m) && Array.isArray(b.elevation_m) && Array.isArray(b.grade_pct) && b.m.length === b.elevation_m.length && b.elevation_m.some((e) => typeof e === "number");
}

export async function fetchIntervalProfile(
  id: string,
  fetcher: (url: string, init?: RequestInit) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }> = (u, i) => fetch(u, i),
): Promise<IntervalProfile | null> {
  try {
    const response = await fetcher(intervalProfileUrl(id), { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const body = unitsFirstDeep(await response.json());
    return looksLikeProfile(body) ? body : null;
  } catch {
    return null;
  }
}

const kept = new Map<string, Promise<IntervalProfile | null>>();

/** The stretch's profile chart, kept once drawn; null where there is none (an error is asked again next hover). */
export function intervalHoverChart(id: string, line: readonly LonLat[] | null, fetcher?: Parameters<typeof fetchIntervalProfile>[1]): () => Promise<ReactElement | null> {
  return async () => {
    let made = kept.get(id);
    if (!made) {
      made = fetchIntervalProfile(id, fetcher);
      made.then((p) => p === null && kept.delete(id), () => kept.delete(id));
      kept.set(id, made);
    }
    const profile = await made;
    if (profile === null) return null;
    const ends = line && line.length >= 2 ? profileEnds(line[0], line[line.length - 1]) : null;
    const along = profile.max_grade_pct === null ? t("Elevation along the stretch.") : t("Elevation along the stretch, steepest {grade}%.", { grade: profile.max_grade_pct.toFixed(0) });
    const summary = `${along}${ends ? ` ${ends.words}` : ""}`;
    return h(ElevationProfileChart, { profile, summary, uid: `hover-interval-${id.replace(/[^A-Za-z0-9_-]/g, "")}`, ends });
  };
}

interface IntervalMap {
  getLayer(id: string): unknown;
  queryRenderedFeatures(box: [[number, number], [number, number]], options: { layers: string[] }): unknown[];
}

/** The stretch's two ends, from its drawn properties (a rendered feature's own line is cut at tile edges). */
export function intervalEnds(p: Record<string, unknown>): LonLat[] | null {
  const n = [p.x0, p.y0, p.x1, p.y1].map(Number);
  return n.every(Number.isFinite) ? [[n[0], n[1]], [n[2], n[3]]] : null;
}

/** The drawn stretch under the mouse (within `slop` px), with its properties; null where none is drawn. */
export function intervalAt(map: IntervalMap, point: { x: number; y: number }, slop: number): { properties: Record<string, unknown> } | null {
  if (!map.getLayer(INTERVALS_LINE_LAYER)) return null;
  const box: [[number, number], [number, number]] = [
    [point.x - slop, point.y - slop],
    [point.x + slop, point.y + slop],
  ];
  const [feature] = map.queryRenderedFeatures(box, { layers: [INTERVALS_LINE_LAYER] }) as { properties?: Record<string, unknown> }[];
  return feature?.properties ? { properties: feature.properties } : null;
}
