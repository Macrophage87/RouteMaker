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
  /** "penalty" (v0.12.0): a work zone that can be ridden through; on the map with no route only (orange). */
  kind: "closed" | "unknown" | "lane" | "penalty";
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

// --- Closures with no route (v0.12.0) -------------------------------------------------------
//
// The owner, 2026-10-23 (Lake Frank): "When a closure happens, we should get one of those red construction symbols",
// "with a red path on the closed parts", "or orange for construction you can get around"; DC's permits off by
// default. GET /api/closures/map answers the closures in force now in the map's view (core.workzones.area_rows):
// asked after the map moves and every few minutes while the page is in front, so one past its end date leaves.

export const AREA_MIN_ZOOM = 11;
export const AREA_POLL_MS = 5 * 60_000;
/** The largest view the server answers (core.workzones.AREA_MAX_*), a hair under. */
export const AREA_MAX_LON = 0.399;
export const AREA_MAX_LAT = 0.299;

export interface View {
  west: number;
  south: number;
  east: number;
  north: number;
}

/**
 * What to ask for the map's view: the view padded to twice its size around its middle, cut to the server's largest,
 * so small moves (the ride's follow camera eases every fix) stay inside what was asked and ask nothing more
 * (`viewInside`). Null when zoomed out.
 */
export function areaClosuresAsk(view: View, zoom: number, permits = false): { path: string; box: View } | null {
  if (zoom < AREA_MIN_ZOOM) return null;
  const cx = (view.west + view.east) / 2;
  const cy = (view.south + view.north) / 2;
  const halfLon = Math.min((view.east - view.west) * 2, AREA_MAX_LON) / 2;
  const halfLat = Math.min((view.north - view.south) * 2, AREA_MAX_LAT) / 2;
  const r = (v: number) => Math.round(v * 1e4) / 1e4;
  const box = { west: r(cx - halfLon), south: r(cy - halfLat), east: r(cx + halfLon), north: r(cy + halfLat) };
  const bbox = [box.west, box.south, box.east, box.north].join(",");
  return { path: `/api/closures/map?bbox=${encodeURIComponent(bbox)}${permits ? "&permits=true" : ""}`, box };
}

/** The request's path for the map's view (`areaClosuresAsk`); null when zoomed out. */
export function areaClosuresPath(view: View, zoom: number, permits = false): string | null {
  return areaClosuresAsk(view, zoom, permits)?.path ?? null;
}

/** Whether the view lies wholly inside what was asked. */
export function viewInside(view: View, box: View | null): boolean {
  return !!box && view.west >= box.west && view.east <= box.east && view.south >= box.south && view.north <= box.north;
}

/** What tells two answers apart for the map: the same ids, ends and wording draw the same, so the map is left alone. */
export function closuresKey(items: readonly ClosureItem[]): string {
  return items.map((i) => `${i.id}|${i.end ?? ""}|${i.when_text}|${i.severity}`).join("\n");
}

/** The answer's closures, each checked; [] when it is not the answer's shape. */
export function parseAreaClosures(value: unknown): ClosureItem[] {
  const list = (value as { closures?: unknown } | null)?.closures;
  if (!Array.isArray(list)) return [];
  return list.filter(
    (c): c is ClosureItem =>
      !!c &&
      typeof c.id === "string" &&
      typeof c.title === "string" &&
      Array.isArray(c.point) &&
      Array.isArray(c.line) &&
      (c.severity === "red" || c.severity === "amber"),
  );
}

/** GET the view's closures; [] when it could not be asked (offline, refused); null when aborted. */
export async function loadAreaClosures(
  path: string,
  signal?: AbortSignal,
  fetcher: (url: string, init?: RequestInit) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u, init) => fetch(u, init),
): Promise<ClosureItem[] | null> {
  try {
    const response = await fetcher(path, { signal, credentials: "same-origin" });
    if (signal?.aborted || !response.ok) return null;
    return parseAreaClosures(await response.json());
  } catch {
    return null;
  }
}

/** The closures to draw: the route's (with its delays and choices), then the view's that the route does not carry. */
export function mergeClosures(route: readonly ClosureItem[], area: readonly ClosureItem[], permits = false): ClosureItem[] {
  const seen = new Set(route.map((item) => item.id));
  return [...route, ...area.filter((item) => !seen.has(item.id) && (permits || item.effect !== "possible"))];
}

/**
 * The closures that get a marker. A reviewer's closure is one zone per road piece ("reviewer-<closure>-<piece>"), so
 * Lake Frank's trail closure was ten barriers in a row: with no route, one marker per closure, on its middle piece,
 * and every piece still drawn red. A route's pieces keep a marker each, since each has its own "Route through anyway".
 */
export function markerItems(items: readonly ClosureItem[]): ClosureItem[] {
  const groups = new Map<string, ClosureItem[]>();
  const out: ClosureItem[] = [];
  for (const item of items) {
    const piece = /^(reviewer-\d+)-(\d+)$/.exec(item.id);
    if (!piece || (item.effect !== "none" && item.effect !== "possible")) {
      out.push(item);
      continue;
    }
    const group = groups.get(piece[1]);
    if (group) group.push(item);
    else {
      groups.set(piece[1], [item]);
      out.push(item);
    }
  }
  return out.map((item) => {
    const piece = /^(reviewer-\d+)-/.exec(item.id);
    const group = piece && (item.effect === "none" || item.effect === "possible") ? groups.get(piece[1]) : undefined;
    if (!group || group.length < 2) return item;
    const order = (i: ClosureItem) => Number(i.id.slice(i.id.lastIndexOf("-") + 1));
    const sorted = [...group].sort((a, b) => order(a) - order(b));
    return sorted[Math.floor((sorted.length - 1) / 2)];
  });
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
        : item.kind === "penalty"
          ? "Construction"
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
        : item.kind === "penalty"
          ? "Construction"
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
