/**
 * Snapping an opened track to the map's streets and paths (PLAN.md, Import: map matching; POST /api/match,
 * core.map_match). Offered in Plan's opened-file section as one action, "Snap to the map's streets", on a
 * track: only the file's line inside the area is sent (no name, time or anything else of the file), and
 * nothing is kept. The snapped line is what fitting follows in place of the file's own (gpxPlan.ts `matched`),
 * so the plan's points sit on ways the router knows and the route is rated and rerouted like any plan; the file
 * itself, its faint line, its download and a saved copy stay as they came.
 */
import { FOLLOW_MAX_POINTS } from "./api.ts";
import { formatDistance } from "./format.ts";
import { MAX_POINTS, type LonLat } from "./geo.ts";
import { IMPORT_START_POINTS, type ImportedPlan } from "./gpxPlan.ts";
import type { PresetId } from "./presets.ts";
import { cumulative, viaPoints } from "./trackMatch.ts";

/** Most points sent (core.map_match.MAX_POINTS; the reference line keeps at most this many). */
export const MATCH_MAX_POINTS = 5000;
/** Below this share of the track on a way, the snap is not used: too much of it is off the map. */
export const MATCH_MIN_SHARE = 0.5;

export const MATCH_ACTION = "Snap to the map's streets";
export const MATCHING_SAID = "Snapping the track to the map's streets and paths…";
export const MATCH_HINT =
  "Snap to the map's streets sends the file's line, and nothing else of it, to RouteMaker's router to find the streets and paths it follows; nothing is kept.";

export type MatchOutcome = { ok: true; line: LonLat[]; share: number } | { ok: false; message: string };

function percent(share: number): number {
  const p = Math.round(share * 100);
  return p === 100 && share < 1 ? 99 : p;
}

/** At most `max` points of `line`, evenly picked, its ends kept; 6 decimals (about 4 in (10 cm)). */
export function thinForMatch(line: readonly LonLat[], max = MATCH_MAX_POINTS): LonLat[] {
  const round = (p: LonLat): LonLat => [Math.round(p[0] * 1e6) / 1e6, Math.round(p[1] * 1e6) / 1e6];
  if (line.length <= max) return line.map(round);
  const out: LonLat[] = [];
  for (let i = 0; i < max; i += 1) out.push(round(line[Math.round((i * (line.length - 1)) / (max - 1))]));
  return out;
}

type Fetch = typeof fetch;

/** The ride the track is snapped for: its ride type, and the switches that choose its graph (as /api/route's). */
export interface MatchRide {
  preset: PresetId;
  /** "Keep to roads, not trails" (or a ride type always so): the no-trail graph, never onto a trail. */
  trailsOff?: boolean;
  /** Electric assist: the e-bike graph, on a ride type that offers it. */
  assist?: boolean;
}

export async function matchTrack(origin: string, line: readonly LonLat[], ride: MatchRide, post: Fetch = fetch): Promise<MatchOutcome> {
  try {
    const response = await post(`${origin}/api/match`, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ points: thinForMatch(line), preset: ride.preset, trails_off: ride.trailsOff === true, assist: ride.assist === true }),
    });
    const body = (await response.json().catch(() => ({}))) as { error?: string; line?: LonLat[]; matched_share?: number };
    if (response.status === 429) return { ok: false, message: "Too many requests from here just now; try again in a minute." };
    if (!response.ok) return { ok: false, message: body.error || "The router did not answer; try again shortly." };
    const share = typeof body.matched_share === "number" ? body.matched_share : 0;
    if (!Array.isArray(body.line) || body.line.length < 2) return { ok: false, message: "No street or path along the track was found." };
    if (share < MATCH_MIN_SHARE) {
      return { ok: false, message: `Only ${percent(share)}% of the track lies on streets and paths the map has for this ride type.` };
    }
    return { ok: true, line: body.line, share };
  } catch {
    return { ok: false, message: "The router could not be reached; try again shortly." };
  }
}

/**
 * The opened plan following the snapped line: its points picked from it as from a track, then fitted to it. No
 * ride type and no sliders, so opening it keeps the ride as it is now (gpxEdit.ts rideAfterImport).
 */
export function matchedPlan(plan: ImportedPlan, line: LonLat[], share: number): ImportedPlan {
  const { dials: _dials, ...rest } = plan;
  return { ...rest, preset: null, matched: { line, share }, points: viaPoints(line, Math.min(IMPORT_START_POINTS, MAX_POINTS), "corners") };
}

/** The longest line followed (core/follow.py MAX_DISTANCE_M, 124 mi): a longer one is planned through its points. */
export const FOLLOW_MAX_M = 200_000;

/**
 * The line a plan follows exactly (POST /api/route `follow`, core/follow.py): the opened file's line, snapped or as it
 * came, while the plan's points are still those the file opened with (or fitting moved them to). Undefined once the
 * rider has changed them or asked for a loop, once the API has said it could not follow this file (`unfollowed`), and
 * for a file with no line or one too long to follow.
 */
export function followLine(
  opened: { imported: Pick<ImportedPlan, "reference" | "matched">; points: readonly LonLat[]; unfollowed?: boolean } | null,
  points: readonly LonLat[],
  loop = false,
): LonLat[] | undefined {
  if (!opened || opened.unfollowed || loop || opened.points.length !== points.length) return undefined;
  if (!opened.points.every((p, i) => p[0] === points[i][0] && p[1] === points[i][1])) return undefined;
  const line = fitLine(opened.imported);
  if (line.length < 2 || (cumulative(line).at(-1) ?? 0) > FOLLOW_MAX_M) return undefined;
  return thinForMatch(line, FOLLOW_MAX_POINTS);
}

/** The line fitting follows: the snapped line once there is one, else the file's own. */
export function fitLine(plan: Pick<ImportedPlan, "reference" | "matched">): LonLat[] {
  return plan.matched?.line ?? plan.reference;
}

/** "Snapped 96% of the track, 12.3 mi (19.8 km), to the map's streets and paths; ..." (US units first). */
export function matchedSaid(matched: { line: readonly LonLat[]; share: number }): string {
  const length = cumulative(matched.line).at(-1) ?? 0;
  return (
    `Snapped ${percent(matched.share)}% of the track to the map's streets and paths, ${formatDistance(length)} in all; ` +
    "the plan now follows the snapped line. The file itself is kept as it came."
  );
}

export function matchFailedSaid(message: string): string {
  return `The track was not snapped. ${message} The plan still follows the file's own track.`;
}
