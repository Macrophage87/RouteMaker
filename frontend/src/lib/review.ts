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
import { streetViewUrl } from "./roadInfo.ts";

type Fetch = typeof fetch;

export type QueueKey = "rebuild" | "disagreement" | "sidepath" | "narrow_rural" | "works_closure" | "rematch" | "painted_lane";
/** Review's own lists: its queues, then the reviews that were in Settings. */
export type ListKey = QueueKey | "suggestions" | "hazards" | "closures";
export type Decision = "accept" | "reject" | "set";

export interface QueueSummary {
  queue: QueueKey;
  label: string;
  build_id: string;
  /** The build the queue was last computed for, and when. */
  computed_for: string;
  computed_at: string | null;
  /** Why the list is empty where it is ("No report from this build"); "" when it was computed. */
  note: string;
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
  /** The lead way of the stretch it was made on (every way of it was ruled together), or null. */
  stretch: number | null;
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
  /** A stretch's: every way's together (core.stress_review.group_stretches). */
  length_m: number;
  length: string;
  /** The ways the row is: a stretch of one road between major junctions with one change, or one way alone. A ruling
   * on the row is a ruling on each. */
  ways: number[];
  pieces: number;
  aadt: number | null;
  bbox: [number, number, number, number] | null;
  geometry: { type: string; coordinates: unknown } | null;
  /** A point on the road: where its street photo is looked up. */
  point: [number, number] | null;
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

export interface Fact {
  label: string;
  value: string;
  source: string | null;
}

export interface RoadDetail {
  osm_way_id: number;
  /** As the map being served holds the road. */
  facts: Fact[];
  /** A rebuild's change: as the build waiting to be swapped in holds it ([] elsewhere). */
  new_facts: Fact[];
  history: { at: string; what: string }[];
}

export interface Filters {
  kind: string;
  source: string;
  area: string;
}

export const NO_FILTERS: Filters = { kind: "", source: "", area: "" };

/** Review's lists in the order the sidebar shows them; Rebuild changes is the default. The learned model's gap list (the
 * roads it rates far from the formula) is to be one more queue here, after Rating disagreements, once the server computes
 * it into the same table; nothing of it exists yet. */
export const LISTS: { key: ListKey; label: string }[] = [
  { key: "rebuild", label: "Rebuild changes" },
  { key: "disagreement", label: "Rating disagreements" },
  { key: "narrow_rural", label: "Narrow rural roads" },
  { key: "sidepath", label: "Side path not mapped" },
  { key: "works_closure", label: "Industrial-area closures" },
  { key: "rematch", label: "Overrides not re-matched" },
  { key: "painted_lane", label: "Painted lanes, agency against formula" },
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

/** A road's own ruling button (the owner, 2026-10-17: "use a keep old and keep new, put the current LTS there so it's
 * easier to see"): a rebuild's names the level each keeps, "Keep old: LTS 2", "Keep new: Avoid"; the rest as
 * decisionLabel. The batch's buttons keep decisionLabel's, the selected roads' levels being their own. */
export function rulingLabel(road: Pick<ReviewRoad, "queue" | "old_step" | "old_closed" | "new_step" | "new_closed">, decision: Decision): string {
  const words = decisionLabel(road.queue, decision);
  if (road.queue !== "rebuild" || decision === "set") return words;
  const level = decision === "accept" ? stepText(road.new_step, road.new_closed) : stepText(road.old_step, road.old_closed);
  return level === "—" ? words : `${words}: ${level}`;
}

/** Google Street View at the road's own point (the server's, on the line), as the road panel links it; null with none. */
export function roadStreetViewUrl(road: Pick<ReviewRoad, "point">): string | null {
  const p = road.point;
  return Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === "number" && Number.isFinite(n)) ? streetViewUrl([p[0], p[1]]) : null;
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

/** "3 road pieces" for a stretch of more than one way, else "". */
export function piecesText(road: Pick<ReviewRoad, "pieces">): string {
  return road.pieces > 1 ? `${road.pieces.toLocaleString("en-US")} road pieces` : "";
}

/** A row's accessible name (the road's button): its name first, as shown, then how many pieces, its length (miles
 * first, kilometres in brackets) and its change: "Oak Street, 3 road pieces, 0.32 mi (0.52 km): LTS 2 to LTS 4". */
export function roadRowLabel(road: Pick<ReviewRoad, "name" | "osm_way_id" | "queue" | "kind_label" | "reason" | "length" | "pieces">): string {
  const name = road.name || `Way ${road.osm_way_id}`;
  const pieces = piecesText(road);
  const change = road.queue === "rebuild" ? road.kind_label : road.reason || road.kind_label;
  return `${name}${pieces ? `, ${pieces}` : ""}, ${road.length}${change ? `: ${change}` : ""}`;
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

/**
 * Each list's colour on the map: the Okabe-Ito palette, which stays apart for every common kind of colour blindness,
 * with a dash pattern of its own as well, so no list is told by its colour alone (the toggles beside the map show
 * both). Drawn with a light halo, above the stress lines.
 */
export const QUEUE_STYLE: Record<QueueKey, { colour: string; colourName: string; dash: number[] | null; pattern: string }> = {
  rebuild: { colour: "#0072B2", colourName: "blue", dash: null, pattern: "solid" },
  disagreement: { colour: "#D55E00", colourName: "vermilion", dash: null, pattern: "solid" },
  narrow_rural: { colour: "#009E73", colourName: "green", dash: [2, 1], pattern: "long dashes" },
  sidepath: { colour: "#CC79A7", colourName: "pink", dash: [1, 1], pattern: "short dashes" },
  works_closure: { colour: "#56B4E9", colourName: "sky blue", dash: [3, 1, 1, 1], pattern: "dash and dot" },
  rematch: { colour: "#E69F00", colourName: "orange", dash: [0.5, 1], pattern: "dots" },
  painted_lane: { colour: "#000000", colourName: "black", dash: [4, 1, 1, 1, 1, 1], pattern: "dash and two dots" },
};

export const QUEUES: QueueKey[] = ["rebuild", "disagreement", "narrow_rural", "sidepath", "works_closure", "rematch", "painted_lane"];

/**
 * What Review's map shows of the view (GET /api/review/map): the roads of the lists switched on inside it, up to the
 * server's cap, the largest first. Far out, the roads near one another are one badge with their count, and only a road
 * alone is drawn; below a street's zoom the lines are simplified, with a dot a road.
 */
export interface MapView {
  zoom: number;
  detail: "low" | "high";
  /** More roads were in view than one answer holds: zoom in for the rest. */
  truncated: boolean;
  lines: { type: "FeatureCollection"; features: MapFeature[] };
  dots: { type: "FeatureCollection"; features: MapFeature[] };
  badges: { type: "FeatureCollection"; features: { type: "Feature"; geometry: unknown; properties: { count: number } }[] };
}

export interface MapFeature {
  type: "Feature";
  geometry: unknown;
  properties: { way: number; queue: QueueKey; size?: number; ruled: boolean };
}

/** A road in the lists' order: its list and its way. */
export interface Spot {
  queue: QueueKey;
  way: number;
}

/** A view is at most this many wide screens across at its zoom (core.stress_review.view_refusal: wider is refused). */
export const VIEW_MAX_SCREENS = 4;
const SCREEN_PX = 1920;
/** MapLibre's world is 512 pixels wide at zoom 0. */
const TILE_PX = 512;

/** The zoom the server is sent: to a tenth, never above the map's, so the widest view it allows is never narrower than
 * the one asked for. */
export function viewZoom(zoom: number): number {
  return Math.max(0, Math.floor(zoom * 10) / 10);
}

/** The widest view, in degrees of longitude, the server draws at `zoom`. */
export function maxViewWidth(zoom: number): number {
  return (VIEW_MAX_SCREENS * SCREEN_PX * 360) / (TILE_PX * 2 ** zoom);
}

/** The map's view as the server takes it: west, south, east, north inside the world's bounds, west never past east and
 * south never past north (a view across the date line is the whole width), rounded to about a metre, and at `zoom` no
 * wider than the server draws (narrowed about its middle). */
export function viewBox(west: number, south: number, east: number, north: number, zoom = 0): [number, number, number, number] {
  const round = (v: number) => Math.round(v * 1e5) / 1e5;
  const clamp = (v: number, limit: number) => Math.max(-limit, Math.min(limit, v));
  const whole = east - west >= 360 || clamp(west, 180) > clamp(east, 180);
  let w = whole ? -180 : clamp(west, 180);
  let e = whole ? 180 : clamp(east, 180);
  // Rounded inwards a little, so the rounding never takes it past the widest.
  const widest = maxViewWidth(viewZoom(zoom)) - 2e-5;
  if (e - w > widest) {
    const middle = (w + e) / 2;
    w = middle - widest / 2;
    e = middle + widest / 2;
  }
  const s = clamp(Math.min(south, north), 90);
  const n = clamp(Math.max(south, north), 90);
  return [round(w), round(s), round(e), round(n)];
}

/** What the map draws of a view while a newer one is asked for: only the lists still switched on (a list switched off
 * goes at once, and stays gone if the request fails); the count badges, which count every list asked for, only while
 * all of those are still on. */
export function drawnOf(view: MapView | null, asked: readonly QueueKey[], drawn: readonly QueueKey[]): Pick<MapView, "lines" | "dots" | "badges"> | null {
  if (!view) return null;
  const on = new Set(drawn);
  const keep = (f: MapFeature) => on.has(f.properties.queue);
  return {
    lines: { type: "FeatureCollection", features: view.lines.features.filter(keep) },
    dots: { type: "FeatureCollection", features: (view.dots?.features ?? []).filter(keep) },
    badges: asked.every((q) => on.has(q)) ? view.badges : { type: "FeatureCollection", features: [] },
  };
}

/** Keys a typed word goes to: Alt+Shift+N is left to them there (a text box, a text area, an editable region). */
export function typingIn(target: unknown): boolean {
  const t = target as { tagName?: string; type?: string; isContentEditable?: boolean } | null;
  if (!t) return false;
  if (t.isContentEditable) return true;
  const tag = (t.tagName ?? "").toUpperCase();
  if (tag === "TEXTAREA") return true;
  if (tag !== "INPUT") return false;
  return !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file", "image"].includes((t.type ?? "text").toLowerCase());
}

/**
 * Review's announcer: what is said within a moment is said together, in order, so a second message never overwrites
 * the first in the live region before a screen reader has read it.
 */
export function makeAnnouncer(send: (text: string) => void, wait = 80, schedule: (run: () => void, ms: number) => unknown = (run, ms) => setTimeout(run, ms)): (text: string) => void {
  let pending: string[] = [];
  return (text: string) => {
    if (!text) return;
    if (pending.length === 0) {
      schedule(() => {
        const said = pending.join(" ");
        pending = [];
        send(said);
      }, wait);
    }
    if (pending[pending.length - 1] !== text) pending.push(text);
  };
}

/** How long the card waits for a held arrow key to settle before asking for the road's facts and photo. */
export const SETTLE_MS = 250;

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

/** GET /api/review/road/{way}: the facts behind its rating (a rebuild's: the new build's beside the map's) and its history. */
export async function fetchRoadDetail(origin: string, way: number, queue: QueueKey | null = null, run: Fetch = fetch): Promise<RoadDetail | string> {
  const q = queue ? `?${query({ queue })}` : "";
  const r = await call<RoadDetail>(`${origin}/api/review/road/${way}${q}`, { method: "GET" }, null, run);
  return r.ok ? r.body : r.message;
}

/** GET /api/review/map: the lists' roads in the map's view at its zoom (never a whole list). */
export async function fetchMapView(
  origin: string,
  queues: readonly QueueKey[],
  box: [number, number, number, number],
  zoom: number,
  run: Fetch = fetch,
  signal?: AbortSignal,
): Promise<MapView | string> {
  const [west, south, east, north] = box;
  const q = query({ queues: queues.join(","), west, south, east, north, zoom: viewZoom(zoom) });
  const r = await call<MapView>(`${origin}/api/review/map?${q}`, { method: "GET", signal }, null, run);
  return r.ok ? r.body : r.message;
}

export interface NextRequest {
  /** The lists to go through, in Review's order. */
  lists: readonly QueueKey[];
  /** Where it goes from: the road open now (`way` null: the list's start). */
  queue: QueueKey;
  way: number | null;
  direction?: 1 | -1;
  /** Only the roads with no ruling yet (Next discrepancy); every road for Previous and Next road with "all" shown. */
  openOnly?: boolean;
  /** Past the last list, round to the first. */
  wrap?: boolean;
}

/**
 * GET /api/review/next: the next road in the lists' order (the server's, the table's), so Next discrepancy and
 * Previous and Next road from a road off the page never need a list's every way here. Null when there is none.
 */
export async function fetchNext(origin: string, request: NextRequest, run: Fetch = fetch): Promise<Spot | null | string> {
  const q = query({
    lists: request.lists.join(","),
    queue: request.queue,
    way: request.way,
    direction: request.direction ?? 1,
    open_only: request.openOnly ?? true,
    wrap: request.wrap ?? true,
  });
  const r = await call<{ next: { queue: QueueKey; osm_way_id: number } | null }>(`${origin}/api/review/next?${q}`, { method: "GET" }, null, run);
  if (!r.ok) return r.message;
  return r.body.next ? { queue: r.body.next.queue, way: r.body.next.osm_way_id } : null;
}

export interface RulingRequest {
  queue: QueueKey;
  osm_way_ids: number[];
  decision: Decision;
  step?: number;
  /** Private and optional; never filled in from a source's row. */
  reason?: string;
  /** Change LTS to this listed source's level ("Use" on the card): the server names it in the evidence. */
  source?: string;
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
