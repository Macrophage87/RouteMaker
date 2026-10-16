/**
 * Review (the owner, 2026-10-16: "Basically we'd have 3 modes for people who have admin access go/plan/review";
 * "Add a mode that will allow people with admin access the ability to look at these roads and make a ruling"):
 * an instance admin's queues of roads to rule on (core.stress_review), beside the riders' suggestions, hazard
 * reports and closure reports. Desktop first ("Review is mostly designed for on computer, so feel free to show all
 * the different listings available"): every list with its count, a table of the chosen list next to the map, and
 * the chosen road's facts, ratings and history with its ruling buttons (ReviewMode.tsx).
 *
 * Pure apart from the fetches, so the words, the sorting and the requests are tested without a browser.
 */
import { call } from "./suggestions.ts";

type Fetch = typeof fetch;

export type QueueKey = "rebuild" | "disagreement" | "sidepath" | "narrow_rural" | "works_closure" | "rematch";
/** Review's own lists: its queues, then the reviews that were in Settings. */
export type ListKey = QueueKey | "suggestions" | "hazards" | "closures";
export type Decision = "accept" | "reject" | "set";

export interface QueueSummary {
  queue: QueueKey;
  label: string;
  build_id: string;
  total: number;
  reviewed: number;
  wired: boolean;
  kinds: { kind: string; label: string; count: number }[];
  areas: { area: string; count: number }[];
  sources: { source: string; label: string; count: number }[];
}

export interface RatingSource {
  key: string;
  name: string;
  level: number;
  /** An agency whose public use is not yet confirmed: shown in Review only, never deciding. */
  pending: boolean;
}

export interface Ruling {
  id: number;
  queue: QueueKey;
  osm_way_id: number;
  decision: Decision;
  step: number | null;
  reason: string;
  at: string;
  undone: boolean;
  can_undo: boolean;
  summary: string;
}

export interface ReviewRoad {
  queue: QueueKey;
  osm_way_id: number;
  name: string;
  area: string;
  reason: string;
  kind: string;
  kind_label: string;
  old_step: number | null;
  new_step: number | null;
  old_words: string | null;
  new_words: string;
  old_closed: boolean;
  new_closed: boolean;
  old_rule: string | null;
  new_rule: string | null;
  old_source: string | null;
  new_source: string | null;
  sources: RatingSource[];
  ratings: { label: string; value: string; source: string | null }[];
  spread: number | null;
  length_m: number;
  length: string;
  aadt: number | null;
  bbox: [number, number, number, number] | null;
  geometry: { type: string; coordinates: unknown } | null;
  actions: Decision[];
  ruling: Ruling | null;
}

export interface ReviewPage {
  queue: QueueKey;
  build_id: string;
  page: number;
  per_page: number;
  total: number;
  items: ReviewRoad[];
}

export interface RoadDetail {
  osm_way_id: number;
  facts: { label: string; value: string; source: string | null }[];
  history: { at: string; what: string }[];
}

export interface Filters {
  kind: string;
  source: string;
  area: string;
}

export const NO_FILTERS: Filters = { kind: "", source: "", area: "" };

/** Review's lists in the order the sidebar shows them; Rebuild changes is the default. */
export const LISTS: { key: ListKey; label: string }[] = [
  { key: "rebuild", label: "Rebuild changes" },
  { key: "disagreement", label: "Rating disagreements" },
  { key: "narrow_rural", label: "Narrow rural roads" },
  { key: "sidepath", label: "Side path not mapped" },
  { key: "works_closure", label: "Industrial-area closures" },
  { key: "rematch", label: "Overrides not re-matched" },
  { key: "suggestions", label: "Rider suggestions" },
  { key: "hazards", label: "Mass Ride hazard reports" },
  { key: "closures", label: "Closure reports" },
];

export const DEFAULT_LIST: ListKey = "rebuild";

export function isQueue(key: ListKey): key is QueueKey {
  return !["suggestions", "hazards", "closures"].includes(key);
}

/** The ruling buttons' names, by list: a rebuild's change is kept or put back; a closure kept or reopened. */
export function decisionLabel(queue: QueueKey, decision: Decision): string {
  if (decision === "set") return "Set LTS";
  if (queue === "rebuild") return decision === "accept" ? "Keep new" : "Keep old";
  if (queue === "works_closure") return decision === "accept" ? "Keep closed" : "Reopen";
  if (queue === "disagreement") return "Keep current";
  return decision === "accept" ? "Accept" : "Reject";
}

/** A level in a few characters: "LTS 2.5", "Avoid". */
export function stepText(step: number | null, closed = false): string {
  if (closed) return "Closed";
  if (step === null) return "—";
  return step >= 5 ? "Avoid" : `LTS ${step}`;
}

/** The levels Set LTS offers: 1 to 5 by halves, 5 being Avoid. */
export const REVIEW_STEPS = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5];

/** "12 of 601 reviewed". */
export function progressText(reviewed: number, total: number): string {
  return `${reviewed.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} reviewed`;
}

/** A road's heading: its name (or "Way 123"), its area, and why it is listed. */
export function roadHeading(road: Pick<ReviewRoad, "name" | "osm_way_id" | "area" | "kind_label">): string {
  const name = road.name || `Unnamed way ${road.osm_way_id}`;
  return `${name}${road.area ? `, ${road.area}` : ""}: ${road.kind_label}`;
}

/** Cars a day in US style, or "No count". */
export function trafficText(aadt: number | null): string {
  return aadt === null ? "No count" : `${aadt.toLocaleString("en-US")} a day`;
}

/** What is said once a ruling is made (the polite live region). */
export function ruledSaid(road: Pick<ReviewRoad, "name" | "osm_way_id">, ruling: Pick<Ruling, "summary">, next: string | null): string {
  const name = road.name || `Way ${road.osm_way_id}`;
  return `${name}: ${ruling.summary}.${next ? ` Next: ${next}.` : " No more roads in this list."}`;
}

export type SortKey = "score" | "name" | "area" | "old" | "new" | "spread" | "traffic" | "length";

/** The table sorted by a column; "score" is the server's order (size of the change or disagreement × traffic). */
export function sortRoads(roads: readonly ReviewRoad[], key: SortKey, ascending: boolean): ReviewRoad[] {
  if (key === "score") return ascending ? [...roads].reverse() : [...roads];
  const value = (r: ReviewRoad): number | string => {
    switch (key) {
      case "name":
        return (r.name || "").toLowerCase();
      case "area":
        return r.area.toLowerCase();
      case "old":
        return r.old_step ?? -1;
      case "new":
        return r.new_closed ? 6 : (r.new_step ?? -1);
      case "spread":
        return r.spread ?? Math.abs((r.new_step ?? 0) - (r.old_step ?? 0));
      case "traffic":
        return r.aadt ?? -1;
      case "length":
        return r.length_m;
    }
  };
  const sorted = [...roads].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    return x < y ? -1 : x > y ? 1 : a.osm_way_id - b.osm_way_id;
  });
  return ascending ? sorted : sorted.reverse();
}

/** The overlay's colour by the size of the disagreement or change: amber for a step, red for two or more. */
export function sizeColour(size: number): string {
  if (size >= 2) return "#c62828";
  if (size >= 1) return "#b26a00";
  return "#5c6bc0";
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== "" && v !== null && v !== undefined) q.set(k, String(v));
  return q.toString();
}

/** GET /api/review/queues. */
export async function fetchQueues(origin: string, run: Fetch = fetch): Promise<QueueSummary[] | string> {
  const r = await call<{ queues: QueueSummary[] }>(`${origin}/api/review/queues`, { method: "GET" }, null, run);
  return r.ok ? r.body.queues : r.message;
}

/** GET /api/review/items: a page of a list, the roads with no ruling yet unless `all`. */
export async function fetchRoads(
  origin: string,
  queue: QueueKey,
  filters: Filters,
  options: { page?: number; perPage?: number; all?: boolean; way?: number } = {},
  run: Fetch = fetch,
): Promise<ReviewPage | string> {
  const q = query({ queue, ...filters, page: options.page ?? 1, per_page: options.perPage ?? 50, open_only: !options.all, way: options.way });
  const r = await call<ReviewPage>(`${origin}/api/review/items?${q}`, { method: "GET" }, null, run);
  return r.ok ? r.body : r.message;
}

/** GET /api/review/road/{way}: the facts behind its rating and its history. */
export async function fetchRoadDetail(origin: string, way: number, run: Fetch = fetch): Promise<RoadDetail | string> {
  const r = await call<RoadDetail>(`${origin}/api/review/road/${way}`, { method: "GET" }, null, run);
  return r.ok ? r.body : r.message;
}

/** GET /api/review/map: the list's roads in the box, for the overlay. */
export async function fetchOverlay(
  origin: string,
  queue: QueueKey,
  filters: Filters,
  box: { west: number; south: number; east: number; north: number },
  run: Fetch = fetch,
): Promise<{ type: "FeatureCollection"; features: unknown[] } | string> {
  const r = await call<{ type: "FeatureCollection"; features: unknown[] }>(`${origin}/api/review/map?${query({ queue, ...filters, ...box })}`, { method: "GET" }, null, run);
  return r.ok ? r.body : r.message;
}

export interface RulingRequest {
  queue: QueueKey;
  osm_way_ids: number[];
  decision: Decision;
  step?: number;
  /** Private and optional; never filled in from a source's row. */
  reason?: string;
}

export interface RulingAnswer {
  rulings: Ruling[];
  refused: { osm_way_id: number; error: string }[];
  generation: number | null;
  message: string;
}

/** POST /api/review/rulings. */
export async function sendRuling(origin: string, request: RulingRequest, csrf: string | null, run: Fetch = fetch): Promise<{ ok: true; body: RulingAnswer } | { ok: false; message: string }> {
  const r = await call<RulingAnswer>(`${origin}/api/review/rulings`, { method: "POST", body: JSON.stringify(request) }, csrf, run);
  return r.ok ? r : { ok: false, message: r.message };
}

/** POST /api/review/rulings/{id}/undo. */
export async function undoRuling(origin: string, id: number, csrf: string | null, run: Fetch = fetch): Promise<{ ok: true; body: { ruling: Ruling; generation: number | null; message: string } } | { ok: false; message: string }> {
  const r = await call<{ ruling: Ruling; generation: number | null; message: string }>(`${origin}/api/review/rulings/${id}/undo`, { method: "POST", body: "{}" }, csrf, run);
  return r.ok ? r : { ok: false, message: r.message };
}
