/**
 * A tapped mountain-bike trail's elevation profile in the road panel (the owner, 2026-10-19: "Include an
 * elevation profile of the trail if possible"). GET /api/trails/{way}/profile (core.trailprofile): the router's
 * USGS 3DEP heights along the trail's OSM way, which is the trail between two junctions or the whole trail where
 * it is mapped as one, so the panel calls it "this section". Drawn with the climb card's chart
 * (lib/climbCard.ts ElevationProfileChart), whose text alternative is the summary ("This section: 0.6 mi (1.0 km),
 * up 120 ft (37 m), down 80 ft (24 m), steepest 14%.").
 *
 * Written with createElement so a test renders it, as climbCard.ts.
 */
import { createElement as h, useEffect, useState, type ReactElement } from "react";
import { ElevationProfileChart, gradeText, profileEnds } from "./climbCard.ts";
import { formatClimb, formatDistance } from "./format.ts";

/** GET /api/trails/{way}/profile (core.api.TrailProfileOut). */
export interface TrailProfile {
  way: number;
  length_m: number;
  gain_m: number;
  loss_m: number;
  max_grade_pct: number | null;
  interval_m: number;
  m: number[];
  elevation_m: (number | null)[];
  grade_pct: (number | null)[];
  /** The way's first and last points, [lon, lat]: the chart's left and right ends (older answers have neither). */
  start?: [number, number] | null;
  end?: [number, number] | null;
}

export type TrailProfileState = { kind: "loading" } | { kind: "ready"; profile: TrailProfile } | { kind: "none" } | { kind: "error" };

export const TRAIL_PROFILE_HEADING = "Elevation";
export const TRAIL_PROFILE_LOADING = "Loading the elevation profile…";
export const TRAIL_PROFILE_ERROR = "The elevation profile is not available right now.";

export function trailProfileUrl(way: number): string {
  return `/api/trails/${encodeURIComponent(String(way))}/profile`;
}

function looksLikeProfile(body: unknown): body is TrailProfile {
  const b = body as Partial<TrailProfile> | null;
  return (
    !!b &&
    typeof b.length_m === "number" &&
    typeof b.gain_m === "number" &&
    typeof b.loss_m === "number" &&
    Array.isArray(b.m) &&
    Array.isArray(b.elevation_m) &&
    Array.isArray(b.grade_pct) &&
    b.m.length === b.elevation_m.length &&
    b.m.length === b.grade_pct.length &&
    b.elevation_m.some((e) => typeof e === "number")
  );
}

/** Ask the API: ready, none (not a drawn trail, or no heights) or error (try later). */
export async function fetchTrailProfile(
  way: number,
  signal?: AbortSignal,
  fetcher: (url: string, init?: RequestInit) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }> = (u, i) => fetch(u, i),
): Promise<TrailProfileState> {
  try {
    const response = await fetcher(trailProfileUrl(way), { headers: { Accept: "application/json" }, signal });
    if (response.status === 404) return { kind: "none" };
    if (!response.ok) return { kind: "error" };
    const body = await response.json();
    return looksLikeProfile(body) ? { kind: "ready", profile: body } : { kind: "error" };
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") throw error;
    return { kind: "error" };
  }
}

/** The profile in words: its length, climbing, descending and steepest grade, US units first. */
export function trailProfileSummary(p: Pick<TrailProfile, "length_m" | "gain_m" | "loss_m" | "max_grade_pct">): string {
  const steepest = p.max_grade_pct === null ? "" : `, steepest ${gradeText(p.max_grade_pct)}`;
  return `This section: ${formatDistance(p.length_m)}, up ${formatClimb(p.gain_m)}, down ${formatClimb(p.loss_m)}${steepest}.`;
}

/** The panel's elevation part for one trail way: asked once the panel shows the trail; says nothing where there is none. */
export function TrailProfileView({ way, uid }: { way: number; uid: string }): ReactElement | null {
  const [state, setState] = useState<TrailProfileState>({ kind: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    fetchTrailProfile(way, controller.signal).then(setState, () => undefined);
    return () => controller.abort();
  }, [way]);
  return h(TrailProfileBody, { state, uid });
}

/** What the elevation part shows for a state (rendered alone by a test). */
export function TrailProfileBody({ state, uid }: { state: TrailProfileState; uid: string }): ReactElement | null {
  if (state.kind === "none") return null;
  return h(
    "section",
    { className: "road-info-trail-profile", "aria-labelledby": `${uid}-elevation` },
    h("h3", { id: `${uid}-elevation` }, TRAIL_PROFILE_HEADING),
    state.kind === "loading" && h("p", { className: "hint" }, TRAIL_PROFILE_LOADING),
    state.kind === "error" && h("p", { className: "hint" }, TRAIL_PROFILE_ERROR),
    state.kind === "ready" && h(TrailProfileChart, { profile: state.profile, uid }),
  );
}

/** The trail's chart, with the compass point at each end where the answer has the way's ends. */
export function TrailProfileChart({ profile, uid }: { profile: TrailProfile; uid: string }): ReactElement {
  const ends = profile.start && profile.end ? profileEnds(profile.start, profile.end) : null;
  const summary = trailProfileSummary(profile);
  return h(ElevationProfileChart, { profile, summary: ends ? `${summary} ${ends.words}` : summary, uid, ends });
}
