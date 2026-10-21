/**
 * The hover cards of a climb and a mountain-bike trail (the owner, 2026-10-20: "Add the hover to climbs too" and
 * "Basically they would work sort of like how our metros do now."): as a station's, a small card under the mouse with
 * the feature's name and a line about it, and a click opens the whole card (the climb card, the trail's road panel).
 * Mouse only: a tap opens the card at once, and the keyboard reaches both cards as before.
 */
import { createElement as h, type ReactElement } from "react";
import { ClimbProfileChart, climbTitle, fetchClimbProfile } from "./climbCard.ts";
import { categoryName, climbLength, type Climb } from "./climbs.ts";
import { formatClimb } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { fetchSegmentInfo } from "./roadInfo.ts";
import { TrailProfileChart, fetchTrailProfile } from "./trailProfile.ts";
import { MTB_LEVEL_OPTIONS } from "./mtbMode.ts";
import { MTB_LEVELS } from "../stressStyle.js";

export interface HoverWords {
  /** Distinguishes one card from another, so the card is built only when it changes. */
  key: string;
  title: string;
  detail: string;
}

/** "Foxville Road up Catoctin Mountain" / "Category 3, 2.1 miles (3.4 km), gains 410 ft (125 m) at 4.6%". */
export function climbHoverWords(c: Climb): HoverWords {
  return {
    key: `climb|${c.id}`,
    title: climbTitle(c),
    // An unnamed climb's title is its category already ("Category 4 climb").
    detail: `${c.name ? `${categoryName(c.category)}, ` : ""}${climbLength(c.lengthM)}, gains ${formatClimb(c.gainM)} at ${c.gradePct.toFixed(1)}%`,
  };
}

/**
 * A trail's name (the stress tiles' `name`, which they carry on mountain-bike trails: `mtb_name` in the table; else
 * "Mountain-bike trail"), then its difficulty and what that is based on (the owner, 2026-10-20: "You'd see trail name,
 * then the difficulty rating and what it's based on"): "Level 1 (green): rated S1 or IMBA 1 in OpenStreetMap", as the
 * road panel's "Mountain-bike difficulty" row says it, or that it is not rated.
 */
/** `way` names the drawn way, so the card is rebuilt (at its own point, with its own profile) on the next way along. */
export function trailHoverWords(properties: Record<string, unknown>, way = ""): HoverWords {
  const named = typeof properties.name === "string" ? properties.name.trim() : "";
  const level = MTB_LEVEL_OPTIONS.find((option) => option.level === Number(properties.mtb_level));
  const scale = level ? MTB_LEVELS.find((l: { level: number }) => l.level === level.level)?.scale : undefined;
  const title = named || "Mountain-bike trail";
  const detail = level ? `${level.label}: rated ${scale} in OpenStreetMap` : "Not rated: no difficulty is mapped for this trail";
  return { key: `trail|${way}|${title}|${level?.level ?? ""}`, title, detail };
}

// --- The profile in the card ---------------------------------------------------------------------------------------

/** An id-safe uid for a chart's patterns. */
const uidOf = (key: string) => `hover-${key.replace(/[^A-Za-z0-9_-]/g, "")}`;

const climbCharts = new Map<string, Promise<ReactElement | null>>();

/** The climb's profile chart (GET /api/climbs/{id}/profile), kept once drawn; null where there is none. */
export function climbHoverChart(c: Climb, fetcher?: Parameters<typeof fetchClimbProfile>[1]): () => Promise<ReactElement | null> {
  return () => {
    const kept = climbCharts.get(c.id);
    if (kept) return kept;
    const made = fetchClimbProfile(c.id, fetcher).then((state) =>
      state.kind === "ready" ? h(ClimbProfileChart, { climb: c, profile: state.profile, uid: uidOf(c.id) }) : null,
    );
    // An error is not kept: the next hover asks again.
    made.then((element) => element === null && climbCharts.delete(c.id), () => climbCharts.delete(c.id));
    climbCharts.set(c.id, made);
    return made;
  };
}

const trailCharts = new Map<number, Promise<ReactElement | null>>();

/**
 * The trail's profile chart: which OSM way the trail at `point` is (GET /api/segment-info, as a click asks), then its
 * heights (GET /api/trails/{way}/profile), kept by way once drawn; null where there is none.
 */
export function trailHoverChart(origin: string, point: LonLat): () => Promise<ReactElement | null> {
  return async () => {
    const info = await fetchSegmentInfo(origin, point, undefined, false, true);
    const way = info.kind === "ready" && info.info.found ? (info.info.osm_way_id ?? null) : null;
    if (way === null) return null;
    const kept = trailCharts.get(way);
    if (kept) return kept;
    const made = fetchTrailProfile(way).then((state) => (state.kind === "ready" ? h(TrailProfileChart, { profile: state.profile, uid: uidOf(String(way)) }) : null));
    made.then((element) => element === null && trailCharts.delete(way), () => trailCharts.delete(way));
    trailCharts.set(way, made);
    return made;
  };
}
