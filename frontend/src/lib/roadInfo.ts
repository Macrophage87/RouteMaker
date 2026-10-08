/**
 * The map's road panel (OWNER-DECISIONS 441, 441a): a right-click on a computer, a long
 * press on a phone, or the keyboard's way to the road at the map's centre (the
 * "Road info" button on the map, or I with the map focused) opens a dialog of what
 * RouteMaker knows of the nearest road or path (GET /api/segment-info; core.segment_info)
 * with a bottom row of links drawn as buttons: Street View and Edit in OSM (441m), and
 * later Change LTS for an admin. Read only: changing a road's stress is a later release
 * (441g-441l).
 *
 * The panel opens compact (owner feedback: "a bit wordy and I have to scroll"): the
 * name and kind, then a short summary list - one line a fact, no source under each,
 * a line left out rather than "none" - and the actions; every figure with its source
 * is behind a closed "Details and sources" disclosure.
 *
 * The pure half: the request, the Street View link (on the road, 441o), which sections and summary lines
 * show, what the live region says, and the long press's own timing. RoadInfoDialog.tsx draws it; MapView.tsx
 * listens for the gestures.
 */
import { MAX_POINTS, type LonLat } from "./geo.ts";
import { formatRadius } from "./format.ts";
import { applyPlace, choicesFor, type PlaceChoice } from "./geocode.ts";
import { pointName } from "./summary.ts";

export interface InfoRow {
  label: string;
  value: string;
  source: string | null;
}

export interface InfoSection {
  id: "road" | "stress" | "traffic" | "riding" | "access" | "mass";
  heading: string;
  rows: InfoRow[];
}

/** One line of the compact summary: "Traffic stress: LTS 3 · For experienced cyclists". */
export interface SummaryRow {
  id: string;
  label: string;
  value: string;
}

export interface SegmentInfo {
  found: boolean;
  title: string;
  /** The kind of way in a few words ("Main road"); absent from an older API. */
  kind?: string | null;
  /** The compact lines; absent from an older API, when the details open instead. */
  summary?: SummaryRow[];
  tier: number | null;
  open: boolean | null;
  osm_way_id: number | null;
  distance_m: number | null;
  /** The nearest point on the way itself, [lon, lat], where Street View opens (441o); absent from an older API. */
  on_way?: [number, number] | null;
  sections: InfoSection[];
  attribution: string[];
}

/** Where the panel was asked for: a spot the rider pointed at, or the map's centre by keyboard. */
export type InfoOrigin = "spot" | "centre";

export interface InfoRequest {
  point: LonLat;
  origin: InfoOrigin;
}

/**
 * The panel's request once the dialog showing `closed` has fired its `close` event. The
 * event is queued as a task after `dialog.close()`, so it can land after a newer request
 * (Escape, then I at once): that newer one stays open; only the request that closed goes.
 * The App's state updater calls this, so it compares against the latest request even
 * when that has not rendered yet.
 */
export function requestAfterClose(current: InfoRequest | null, closed: InfoRequest | null): InfoRequest | null {
  return current === closed ? null : current;
}

/**
 * Whether an ask for the road panel is the same gesture asking again (a phone's long press
 * is also its contextmenu), `lastSpotAt` the last pointer ask's time. Only a pointer gesture
 * repeats itself: I on the map is always a new ask, even straight after a right-click's
 * panel was closed with Escape.
 */
export function repeatsInfoAsk(origin: InfoOrigin, now: number, lastSpotAt: number, repeatMs: number): boolean {
  return origin === "spot" && now - lastSpotAt < repeatMs;
}

export type InfoState =
  | { kind: "loading" }
  | { kind: "ready"; info: SegmentInfo }
  | { kind: "error"; message: string };

/** The panel's words. */
export const INFO_TITLE_LOADING = "Looking up the road here";
export const NO_ROAD = "No road here";
/** How far the API looks for a way (core.segment_info.SNAP_RADIUS_M). */
export const SNAP_RADIUS_M = 30;
export const NO_ROAD_HINT = `No road or path within about ${formatRadius(SNAP_RADIUS_M)} of this spot.`;
export const STREET_VIEW_TEXT = "Street View";
/** Street View's one-line privacy note, its link's description. */
export const STREET_VIEW_NOTE = "Opens in a new tab; Google gets this spot only if you follow the link.";
/** The bottom row's OpenStreetMap editor link (OWNER-DECISIONS 441m). */
export const OSM_EDIT_TEXT = "Edit in OSM";
export const OSM_EDIT_NOTE =
  "Opens OpenStreetMap's editor for this way. Needs an OpenStreetMap account; don't copy from Google Street View.";
export const DETAILS_TEXT = "Details and sources";
export const INFO_BUTTON_LABEL = "Road info at map center";
/** The map's small disclosure by its zoom buttons (OWNER-DECISIONS 450) and the two map-center actions it holds. */
export const MAP_TOOLS_LABEL = "Map tools";
export const ADD_AT_CENTRE_LABEL = "Add point at map center";
export const INFO_KEY = "i";
export const INFO_HELP =
  "Right-click the map (or press and hold on a phone) for a short summary of the road there (its traffic stress, speed and whether bikes are allowed), buttons to make the spot your start, end or a stop, and Street View and Edit in OSM links; Details and sources has every figure and where it came from. " +
  `From the keyboard: with the map focused, press I for the road at the center of the map, or open ${MAP_TOOLS_LABEL} (by the map's zoom buttons) for ${INFO_BUTTON_LABEL} and ${ADD_AT_CENTRE_LABEL}. ` +
  `With NVDA or JAWS, I reaches the map only in focus mode (in browse mode it moves to the next list item); ${MAP_TOOLS_LABEL} works in either.`;
/** How long a finger must rest, unmoved, for a long press. */
export const LONG_PRESS_MS = 600;
/** How far a finger may drift and still be a long press, not a pan. */
export const LONG_PRESS_SLOP_PX = 10;

/** Google's public Street View link for a spot (no key, no code of theirs in the app). */
export function streetViewUrl([lon, lat]: LonLat): string {
  const fixed = (n: number) => n.toFixed(6);
  return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${fixed(lat)},${fixed(lon)}`;
}

/**
 * Where the Street View link opens (OWNER-DECISIONS 441o): the nearest point on the road
 * the panel describes, as the API gives it, else (no road, an older API) the spot itself.
 */
export function streetViewPoint(info: SegmentInfo | null, spot: LonLat): LonLat {
  const on = info?.found ? info.on_way : null;
  return Array.isArray(on) && on.length === 2 && on.every((n) => typeof n === "number" && Number.isFinite(n))
    ? [on[0], on[1]]
    : spot;
}

/** OpenStreetMap's editor for the way, or null when the answer names no way. */
export function osmEditUrl(info: SegmentInfo): string | null {
  const way = info.osm_way_id;
  return info.found && typeof way === "number" && Number.isSafeInteger(way) && way > 0
    ? `https://www.openstreetmap.org/edit?way=${way}`
    : null;
}

/** One of the top row's buttons (OWNER-DECISIONS 441n): what it does, and why it cannot, if it cannot. */
export interface SpotAction {
  choice: PlaceChoice;
  text: string;
  /** Why the button is unavailable now, said as its description; null when it is available. */
  unavailable: string | null;
}

export const SPOT_ACTION_TEXT: Record<PlaceChoice, string> = {
  start: "Set as start",
  end: "Set as end",
  via: "Add as stop",
};

/**
 * The top row for a plan of `count` points: Set as start, Set as end, Add as stop, each
 * available as the search's Start / Destination / Stop choice is (`choicesFor`), else
 * with the reason it is not. A loop finishes at its start, so it has no end to set.
 */
export function spotActions(count: number, loop: boolean): SpotAction[] {
  const full = count >= MAX_POINTS;
  const open = choicesFor(count, full, loop);
  const why = (choice: PlaceChoice): string | null => {
    if (open.includes(choice)) return null;
    if (choice === "end") return loop ? "A loop finishes at its start." : "Set a start first.";
    if (full) return `The route has the most points it can (${MAX_POINTS}).`;
    if (count === 0) return "Set a start first.";
    return "Set an end first.";
  };
  return (["start", "end", "via"] as const)
    .filter((choice) => !(loop && choice === "end"))
    .map((choice) => ({ choice, text: SPOT_ACTION_TEXT[choice], unavailable: why(choice) }));
}

/** The plan after a top-row button, the new point's index, and what the live region says. */
export function placeAtSpot(
  points: readonly LonLat[],
  point: LonLat,
  choice: PlaceChoice,
  loop: boolean,
): { next: LonLat[]; said: string } {
  const next = applyPlace(points, point, choice, loop);
  const index = next.indexOf(point);
  return { next, said: `${pointName(index, next.length, loop)} set here.` };
}

/** The request for a spot; the coordinates go in the query only, never in a log (OWNER-DECISIONS 395). */
export function segmentInfoUrl(origin: string, [lon, lat]: LonLat): string {
  return `${origin}/api/segment-info?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}`;
}

/** What the API's refusals mean to a rider. */
export function infoError(status: number): string {
  if (status === 400) return "This spot is outside the area RouteMaker covers.";
  if (status === 429) return "Too many look-ups at once; wait a moment and try again.";
  return "The road information is not available right now; try again shortly.";
}

/** Ask the API about a spot. */
export async function fetchSegmentInfo(origin: string, point: LonLat, signal?: AbortSignal): Promise<InfoState> {
  try {
    const response = await fetch(segmentInfoUrl(origin, point), { signal, headers: { Accept: "application/json" } });
    if (!response.ok) return { kind: "error", message: infoError(response.status) };
    const info = (await response.json()) as SegmentInfo;
    if (!info || typeof info.found !== "boolean" || !Array.isArray(info.sections)) {
      return { kind: "error", message: infoError(500) };
    }
    return { kind: "ready", info };
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") throw error;
    return { kind: "error", message: infoError(500) };
  }
}

/** The sections shown: the Mass Ride capacity only on the Mass Ride map. */
export function shownSections(info: SegmentInfo, massRide: boolean): InfoSection[] {
  return info.sections.filter((s) => s.id !== "mass" || massRide);
}

/** The dialog's heading. */
export function infoHeading(state: InfoState): string {
  if (state.kind === "loading") return INFO_TITLE_LOADING;
  if (state.kind === "error") return "Road information";
  return state.info.found ? state.info.title : NO_ROAD;
}

/** The summary lines shown: the Mass Ride room only on the Mass Ride map. */
export function shownSummary(info: SegmentInfo, massRide: boolean): SummaryRow[] {
  return (info.summary ?? []).filter((r) => r.id !== "mass" || massRide);
}

/** Where the spot is, in a few words. */
export function originText(origin: InfoOrigin): string {
  return origin === "centre" ? "nearest the map center" : "nearest the spot you picked";
}

/** The line under the heading: the kind and where, "Main road, nearest the spot you picked". */
export function subtitle(state: InfoState, origin: InfoOrigin): string {
  const where = originText(origin);
  const kind = state.kind === "ready" && state.info.found ? state.info.kind : null;
  return kind ? `${kind}, ${where}` : where[0].toUpperCase() + where.slice(1);
}

/** A summary value's parts either side of " · ", which is drawn but read as a comma. */
export function valueParts(value: string): string[] {
  return value.split(" · ");
}

/** The way's id and how far it is from the spot, for the details: US units first. */
export function wayRows(info: SegmentInfo): InfoRow[] {
  const rows: InfoRow[] = [];
  if (info.osm_way_id != null) rows.push({ label: "OpenStreetMap way", value: String(info.osm_way_id), source: null });
  if (info.distance_m != null) {
    rows.push({ label: "Distance from the spot", value: formatRadius(info.distance_m), source: null });
  }
  return rows;
}

/** One row, as a sentence for the live region and the row's own reading: "Speed limit: 30 mph, posted (OpenStreetMap)". */
export function rowText(row: InfoRow): string {
  return `${row.label}: ${row.value}${row.source ? ` (source: ${row.source})` : ""}`;
}

/** The stress in a phrase: "LTS 3, for experienced cyclists", or "Avoid". */
function stressPhrase(info: SegmentInfo): string | null {
  const line = info.summary?.find((r) => r.id === "stress")?.value;
  const level = line ?? info.sections.find((s) => s.id === "stress")?.rows.find((r) => r.label === "Level")?.value;
  if (!level) return null;
  const [head, ...rest] = line ? valueParts(level) : level.split(": ");
  const tail = rest.join(": ");
  return tail ? `${head}, ${tail[0].toLowerCase()}${tail.slice(1)}` : head;
}

/**
 * What the live region says once the answer is in, one short sentence: "Connecticut
 * Avenue Northwest: LTS 3, for experienced cyclists." and, on a closed way, "Bikes not
 * allowed here."
 */
export function infoSaid(state: InfoState): string {
  if (state.kind === "loading") return "";
  if (state.kind === "error") return state.message;
  const { info } = state;
  if (!info.found) return `${NO_ROAD}.`;
  const stress = stressPhrase(info);
  const closed = info.open === false ? " Bikes not allowed here." : "";
  return `${info.title}${stress ? `: ${stress}` : ""}.${closed}`;
}

/** Whether a key press asks for the road at the centre: I, unmodified, on the map itself. */
export function isInfoKey(event: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean }): boolean {
  return event.key.toLowerCase() === INFO_KEY && !event.ctrlKey && !event.metaKey && !event.altKey;
}

/**
 * A finger's long press on the map, without taking the pan from it: it starts on one
 * finger's touch, is called off by a second finger, a drift past LONG_PRESS_SLOP_PX, the
 * finger lifting or the map moving, and fires once after LONG_PRESS_MS. Nothing here
 * prevents a default, so the map pans and pinches as it always does.
 */
export class LongPress {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private start: { x: number; y: number } | null = null;
  private readonly fire: (at: { x: number; y: number }) => void;
  private readonly schedule: (run: () => void, ms: number) => ReturnType<typeof setTimeout>;
  private readonly cancelTimer: (timer: ReturnType<typeof setTimeout>) => void;
  constructor(
    fire: (at: { x: number; y: number }) => void,
    schedule: (run: () => void, ms: number) => ReturnType<typeof setTimeout> = (run, ms) => setTimeout(run, ms),
    cancelTimer: (timer: ReturnType<typeof setTimeout>) => void = (timer) => clearTimeout(timer),
  ) {
    this.fire = fire;
    this.schedule = schedule;
    this.cancelTimer = cancelTimer;
  }

  get pending(): boolean {
    return this.timer !== null;
  }

  press(x: number, y: number): void {
    this.cancel();
    this.start = { x, y };
    this.timer = this.schedule(() => {
      this.timer = null;
      const at = this.start;
      this.start = null;
      if (at) this.fire(at);
    }, LONG_PRESS_MS);
  }

  move(x: number, y: number): void {
    if (!this.start) return;
    if (Math.hypot(x - this.start.x, y - this.start.y) > LONG_PRESS_SLOP_PX) this.cancel();
  }

  cancel(): void {
    if (this.timer !== null) this.cancelTimer(this.timer);
    this.timer = null;
    this.start = null;
  }
}
