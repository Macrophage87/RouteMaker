/**
 * Closures on the map (v0.7.0 plan, "Closures on the map"; Stephen 2026-10-15 20:29 UTC: "Have those closures on all
 * maps, and make it clickable, pointing to the source, and state how long the delay would be for. Allow people to
 * bypass the closure.").
 *
 * The route's answer carries the closures in force at the ride (`work_zones.closures`: the Maryland and Virginia
 * work zones, DDOT's permits, MPD's advisories and AlertDC's items) and the park-level "Check before you go" notices
 * (`work_zones.notices`, NPS). MapView.tsx draws them in Go and Plan, in every ride type, with no layer switch (but
 * DDOT's permits, v0.9.1: flagged only, behind Plan's DC permits switch, lib/permitLayer.ts): a red
 * closed stretch with a barrier marker, amber for a blocked bike lane, a park marker for an NPS alert, and a small
 * marker on the line for a closure the rider chose to route through. Each marker is a real button (Tab reaches it, a
 * screen reader names it), and opens a card: what is closed, the source named and linked, when it applies, and the
 * delay on this route ("Detour adds about 4 min", or "No effect on your route"), with "Route through anyway", or
 * "Undo" where the rider already did.
 *
 * "Route through anyway" is per plan (this start and end), never global: the ids go in the request only
 * (`closure_bypass`), in no link, and are forgotten when the start or the end changes.
 *
 * Pure, so it is tested without a map or a DOM.
 */
import type { LonLat } from "./geo.ts";

/**
 * "possible" (v0.9.1): a DDOT permit, which allows closing the road some time in its window. Flagged only: dashed on
 * the map, never routed round, never a heading or a spoken cue (Stephen, 2026-10-19: "We should flag, but not
 * necessarily stop anyone").
 */
export type ClosureEffect = "on_route" | "routed_round" | "bypassed" | "may_still_apply" | "possible" | "none";

/** One closure as the route's answer gives it (core.workzones closure_row). */
export interface ClosureItem {
  id: string;
  source: string;
  source_name: string;
  url: string | null;
  kind: "closed" | "unknown" | "lane";
  severity: "red" | "amber";
  title: string;
  road: string | null;
  when_text: string;
  start: string | null;
  end: string | null;
  effect: ClosureEffect;
  delay_s: number | null;
  effect_text: string;
  can_bypass: boolean;
  bypassed: boolean;
  from_m: number | null;
  to_m: number | null;
  point: LonLat;
  line: LonLat[];
}

/** One "Check before you go" notice (core.workzones notice_row). */
export interface ClosureNotice {
  id: string;
  source: string;
  source_name: string;
  title: string;
  text: string;
  url: string | null;
  area: string;
  area_name: string | null;
  point: LonLat | null;
  category: string | null;
  when_text: string;
}

/** The part of a route's answer this reads. */
export interface WithClosures {
  work_zones?: { closures?: ClosureItem[] | null; notices?: ClosureNotice[] | null } | null;
}

/** The closures to draw; DDOT's permits ("possible") only where the DC permits layer is on (lib/permitLayer.ts). */
export function closuresOf(route: WithClosures | null | undefined, permits = false): ClosureItem[] {
  const items = route?.work_zones?.closures ?? [];
  return permits ? items : items.filter((item) => item.effect !== "possible");
}

/** The notices with a place on the map: the parks' (a District-wide notice has none). */
export function parkNoticesOf(route: WithClosures | null | undefined): ClosureNotice[] {
  return (route?.work_zones?.notices ?? []).filter((n) => n.point !== null);
}

/** Line colours: the route's own red and an amber that both hold 3:1 against the basemap's light and dark greys. */
export const CLOSED_RED = "#c62828";
export const LANE_AMBER = "#b26a00";

/** The closed stretches as map data: a line each, coloured by severity, dashed where it "may still apply". */
export function closureFeatures(items: readonly ClosureItem[]) {
  return {
    type: "FeatureCollection" as const,
    features: items
      .filter((item) => item.line.length >= 2 && !item.bypassed)
      .map((item) => ({
        type: "Feature" as const,
        properties: { id: item.id, severity: item.severity, maybe: item.effect === "may_still_apply" || item.effect === "possible" ? 1 : 0 },
        geometry: { type: "LineString" as const, coordinates: item.line },
      })),
  };
}

/** What the marker is called, to a screen reader: "Road closed: G St NW (permit PA261001). Detour adds about 4 min". */
export function closureMarkerName(item: ClosureItem): string {
  const lead = item.bypassed
    ? "Routed through closure"
    : item.effect === "possible"
      ? item.kind === "lane" ? "Bike lane may be blocked" : "Possible closure"
      : item.kind === "lane"
        ? "Bike lane blocked"
        : "Road closed";
  return `${lead}: ${item.title}. ${item.effect_text.replace(/\.$/, "")}`;
}

export function noticeMarkerName(notice: ClosureNotice): string {
  return `Check before you go, ${notice.area_name ?? "park"}: ${notice.title}`;
}

export const ROUTE_THROUGH_LABEL = "Route through anyway";
export const UNDO_BYPASS_LABEL = "Undo: route round it again";
export const CLOSURE_CARD_CLOSE = "Close closure card";

/** The card's lines, in order, as text (MapView builds the DOM from it; a screen reader reads it in this order). */
export interface ClosureCard {
  heading: string;
  what: string;
  source: { name: string; url: string | null };
  when: string;
  effect: string;
  /** The card's button, or null where it has none (a blocked lane is not routed round, so there is nothing to bypass). */
  action: { label: string; bypass: boolean } | null;
}

export function closureCard(item: ClosureItem): ClosureCard {
  const heading = item.bypassed
    ? "Closure you route through"
    : item.effect === "possible"
      ? item.kind === "lane" ? "Bike lane may be blocked (permit)" : "Possible closure (permit)"
      : item.kind === "lane"
        ? "Bike lane blocked"
        : "Road closed";
  let action: ClosureCard["action"] = null;
  if (item.bypassed) action = { label: UNDO_BYPASS_LABEL, bypass: false };
  else if (item.can_bypass && (item.effect === "routed_round" || item.effect === "may_still_apply" || item.effect === "on_route"))
    action = { label: ROUTE_THROUGH_LABEL, bypass: true };
  return {
    heading,
    what: item.title,
    source: { name: `Source: ${item.source_name}`, url: item.url },
    when: item.when_text,
    effect: item.effect_text,
    action,
  };
}

export function noticeCard(notice: ClosureNotice): ClosureCard {
  return {
    heading: `Check before you go: ${notice.area_name ?? "park"}`,
    what: notice.title,
    source: { name: `Source: ${notice.source_name}${notice.category ? ` (${notice.category})` : ""}`, url: notice.url },
    when: notice.when_text,
    effect: notice.text,
    action: null,
  };
}

/** The rider's bypassed closures, for the plan they were chosen on (its start and end). */
export interface Bypass {
  plan: string;
  ids: string[];
}

/** A plan's identity for the bypass: its start and end. A via moved keeps it; a new start or end forgets it. */
export function bypassPlanKey(points: readonly LonLat[]): string {
  if (points.length < 2) return "";
  const a = points[0];
  const b = points[points.length - 1];
  return `${a[0]},${a[1]}>${b[0]},${b[1]}`;
}

/** The ids in force for this plan: none where they were chosen on another. */
export function bypassFor(bypass: Bypass | null, plan: string): string[] {
  return bypass && plan && bypass.plan === plan ? bypass.ids : [];
}

/** "Route through anyway" (on) or Undo (off) for one closure. */
export function toggleBypass(bypass: Bypass | null, plan: string, id: string, on: boolean): Bypass {
  const ids = bypassFor(bypass, plan).filter((x) => x !== id);
  return { plan, ids: on ? [...ids, id].sort() : ids };
}

/** What is said when the choice is made, before the route is planned again. */
export function bypassSaid(item: Pick<ClosureItem, "title">, on: boolean): string {
  return on ? `Routing through ${item.title}. Planning again.` : `Routing round ${item.title} again. Planning again.`;
}
