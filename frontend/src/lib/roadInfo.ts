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
import { mapToolsWays } from "./accessMode.ts";
import { applyPlace, choicesFor, type PlaceChoice } from "./geocode.ts";
import { pointName } from "./summary.ts";
import { t } from "./i18n.ts";

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

export interface MoreLink {
  label: string;
  url: string;
  system?: string | null;
}

/**
 * The MORE link the panel shows, or null: only an https link on MORE's own site is shown, so the
 * panel never opens a page the API did not mean.
 */
export function moreLink(info: Pick<SegmentInfo, "found" | "more"> | null | undefined): MoreLink | null {
  const more = info?.found ? info.more : null;
  if (!more || typeof more.url !== "string" || typeof more.label !== "string") return null;
  return more.url.startsWith("https://more-mtb.org/") ? more : null;
}

export interface SegmentInfo {
  found: boolean;
  title: string;
  /** The kind of way in a few words ("Main road"); absent from an older API. */
  kind?: string | null;
  /** The compact lines; absent from an older API, when the details open instead. */
  summary?: SummaryRow[];
  tier: number | null;
  /** The exact step, half steps included (1.5 ... 4.5); absent from an older API. `tier` is its whole level. */
  step?: number | null;
  /** Whether the road data can hold a half step yet; absent from an older API (whole steps only). */
  half_steps?: boolean | null;
  open: boolean | null;
  osm_way_id: number | null;
  distance_m: number | null;
  /** The nearest point on the way itself, [lon, lat], where Street View opens (441o); absent from an older API. */
  on_way?: [number, number] | null;
  /**
   * A mountain-bike trail's link to MORE (Mid-Atlantic Off-Road Enthusiasts): its trail system's page,
   * or MORE's trail guide (docs/MTB-TOPO-PLAN.md, slice 6). Absent on other ways and from an older API.
   */
  more?: MoreLink | null;
  /** A mountain-bike trail the trail layer draws: the panel shows its elevation profile and no traffic lines; absent from an older API. */
  mtb_trail?: boolean;
  /**
   * On a mountain-bike trail, which ride types route through it (core.segment_info trail_routing): "offroad"
   * Gravel, Mountain Goat and Mountain Bike (up to the rider's level); "mtb" Mountain Bike alone (a trail above
   * Gravel's level); null none. Absent from an older API.
   */
  trail_open?: "offroad" | "mtb" | null;
  /** On a mountain-bike trail, the level (1-4) Mountain Bike's hardest-level choice reads it at. */
  trail_level?: number | null;
  sections: InfoSection[];
  attribution: string[];
}

/** Where the panel was asked for: a spot the rider pointed at, or the map's centre by keyboard. */
export type InfoOrigin = "spot" | "centre";

export interface InfoRequest {
  point: LonLat;
  origin: InfoOrigin;
  /**
   * Asked for by a junction card's Suggest a change (OWNER-DECISIONS 232; lib/junctionSuggest.ts): the
   * panel opens the junction's suggestion form straight away, where a rider may suggest.
   */
  junction?: boolean;
  /**
   * A tap on the mountain-bike trail layer's line (the owner, 2026-10-19: "The information should be
   * available when clicked on" and "the plan was to allow people to select particular trail segments and
   * route through them"): the panel describes the trail tapped, ahead of a road beside it, and offers
   * Route through this trail (TRAIL_VIA_TEXT).
   */
  trail?: boolean;
}

/**
 * Go's road card (the owner, 2026-10-28: "Put the route here as a big button on top of the card"): a map tap in Go
 * opens the card, and this button routes to the spot as the tap did before (App's goTo, the destination in place
 * of any before it). Two taps where it was one, so a stray tap never plans a ride.
 */
export const ROUTE_HERE_TEXT = t("Ride here");

/** The trail panel's via button: a via point on the trail, which shapes the route through it (lib/pointKinds.ts). */
export const TRAIL_VIA_TEXT = t("Route through this trail");

/** The rider's ride type and, in Mountain Bike, the hardest level chosen (null otherwise). */
export interface TrailRider {
  rideType: string;
  mtbLevel: number | null;
}

/**
 * Why this ride type's routes do not use a tapped mountain-bike trail, or null where they do (or the way is no
 * trail): only then does the panel offer Route through this trail, since a via point on a trail the router
 * keeps closed lands on the nearest open way instead and the route would skip the trail.
 */
export function trailNotRouted(info: SegmentInfo | null, rider: TrailRider): string | null {
  if (info?.mtb_trail !== true) return null;
  const open = info.trail_open ?? null;
  if (open === null) return "No ride type's routes use this trail.";
  if (rider.rideType === "mountain-bike") {
    const level = info.trail_level ?? null;
    return level !== null && rider.mtbLevel !== null && level > rider.mtbLevel
      ? "Mountain Bike routes skip this trail: it is above the level you chose."
      : null;
  }
  if (open === "offroad" && (rider.rideType === "gravel" || rider.rideType === "mountain-goat")) return null;
  return open === "offroad" ? "Only Gravel, Mountain Goat and Mountain Bike routes use this trail." : "Only Mountain Bike routes use this trail.";
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

/**
 * Whether a finger's lift is the end of a press that opened the road panel (its long press, or the
 * contextmenu a phone sends for one): that lift's click is cancelled, or it would press the panel's
 * button now under the finger (Set as start, say) and close it. `downAt` is when the finger went down
 * (null: no map touch), `spotAt` the last pointer ask's time.
 */
export function liftOpenedInfo(downAt: number | null, spotAt: number): boolean {
  return downAt !== null && spotAt >= downAt;
}

export type InfoState =
  | { kind: "loading" }
  | { kind: "ready"; info: SegmentInfo }
  | { kind: "error"; message: string };

/** The panel's words. */
export const INFO_TITLE_LOADING = t("Looking up the road here");
export const NO_ROAD = t("No road here");
/** The panel's title for a way with no name (core/segment_info.py UNNAMED_ROAD_TITLE and
 * UNNAMED_PATH_TITLE, the route description's words capitalised; a Python test ties them). */
export const UNNAMED_ROAD_TITLE = "Unnamed road";
export const UNNAMED_PATH_TITLE = "Path";
/** With the title an older API gave a path with no name (before v0.7.0: "Unnamed path"). */
export const UNNAMED_TITLES: readonly string[] = [UNNAMED_ROAD_TITLE, UNNAMED_PATH_TITLE, "Unnamed path"];
/** How far the API looks for a way (core.segment_info.SNAP_RADIUS_M). */
export const SNAP_RADIUS_M = 30;
export const NO_ROAD_HINT = `No road or path within about ${formatRadius(SNAP_RADIUS_M)} of this spot.`;
export const STREET_VIEW_TEXT = "Street View";
/** Street View's one-line privacy note, its link's description. */
export const STREET_VIEW_NOTE = t("Opens in a new tab; Google gets this spot only if you follow the link.");
/** The bottom row's OpenStreetMap editor link (OWNER-DECISIONS 441m). */
export const OSM_EDIT_TEXT = t("Edit in OSM");
export const OSM_EDIT_NOTE =
  t("Opens OpenStreetMap's editor for this way. Needs an OpenStreetMap account; don't copy from Google Street View.");
export const DETAILS_TEXT = t("Details and sources");
export const INFO_BUTTON_LABEL = t("Road info at map center");
/** The map's small disclosure by its zoom buttons (OWNER-DECISIONS 450) and the two map-center actions it holds. */
export const MAP_TOOLS_LABEL = t("Map tools");
export const ADD_AT_CENTRE_LABEL = t("Add point at map center");
/** The same button in Go, where the spot is the destination (lib/appMode.ts goTapSetsEnd). */
export const SET_END_AT_CENTRE_LABEL = t("Set destination at map center");
export const INFO_KEY = "i";
/**
 * The help for the road panel. The keyboard's way in names Map tools, which is on the page only in
 * accessibility mode (455): off, it says to turn the mode on first. INFO_HELP is the mode-on text.
 * One short line each (P8), the phone's gesture on a phone (`touch`); the keyboard's lines on a computer, and in
 * accessibility mode on any device.
 */
export function infoHelp(accessMode: boolean, go = false, touch = false): string[] {
  const ways = mapToolsWays(accessMode, go);
  const keys =
    touch && !accessMode
      ? []
      : [
          `From the keyboard: with the map focused, press I for the road at the center of the map, or ${ways.roadAndAdd}.`,
          `With NVDA or JAWS, I reaches the map only in focus mode (in browse mode it moves to the next list item); ${accessMode ? "" : "in accessibility mode, "}${MAP_TOOLS_LABEL} works in either.`,
        ];
  return [
    touch
      ? t("Press and hold the map for the road there: its stress, speed and whether bikes may ride, and buttons to start, end or stop there.")
      : t("Right-click the map for the road there: its stress, speed and whether bikes may ride, and buttons to start, end or stop there."),
    t("Street View and Edit in OSM are there too; Details and sources has every figure and where it came from."),
    ...keys,
  ];
}
export const INFO_HELP = infoHelp(true).join(" ");
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
 * with the reason it is not. In a loop Set as end is there too: it ends the ride there (placeAtSpot).
 * `startKnown`: Go, whose start is the rider's location before the plan has a point (the owner, 2026-10-28):
 * the row is as for a plan with its start, so Set as end is open (routed from the location, App's goTo).
 */
export function spotActions(points: number, loop: boolean, startKnown = false): SpotAction[] {
  const count = points === 0 && startKnown ? 1 : points;
  const full = count >= MAX_POINTS;
  // In a loop, Set as end ends the ride there and turns the loop off (Stephen 2026-10-20: "allow an end to be set,
  // stopping the loop"); it adds a point, so not on a full plan.
  const open = [...choicesFor(count, full, loop), ...(loop && count >= 1 && !full ? (["end"] as const) : [])];
  const why = (choice: PlaceChoice): string | null => {
    if (open.includes(choice)) return null;
    if (choice === "end" && count === 0) return "Set a start first.";
    if (full) return `The route has the most points it can (${MAX_POINTS}).`;
    if (count === 0) return "Set a start first.";
    return "Set an end first.";
  };
  return (["start", "end", "via"] as const).map((choice) => ({ choice, text: SPOT_ACTION_TEXT[choice], unavailable: why(choice) }));
}

/** What is said when an end set on a loop turns the loop off. */
export const LOOP_ENDED_SAID = t("End set here. Loop off: the ride ends here.");

/** The plan after a top-row button, the new point's index, and what the live region says. */
export function placeAtSpot(
  points: readonly LonLat[],
  point: LonLat,
  choice: PlaceChoice,
  loop: boolean,
): { next: LonLat[]; said: string; loopOff?: true } {
  // An end set on a loop: after the start and the stops, and the loop off, in one edit (App placeSpot).
  if (loop && choice === "end" && points.length >= 1) return { next: [...points, point], said: LOOP_ENDED_SAID, loopOff: true };
  const next = applyPlace(points, point, choice, loop);
  const index = next.indexOf(point);
  return { next, said: `${pointName(index, next.length, loop)} set here.` };
}

/** The request for a spot; the coordinates go in the query only, never in a log (OWNER-DECISIONS 395). */
export function segmentInfoUrl(origin: string, [lon, lat]: LonLat, trail = false): string {
  return `${origin}/api/segment-info?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}${trail ? "&trail=true" : ""}`;
}

/** What the API's refusals mean to a rider. */
export function infoError(status: number): string {
  if (status === 400) return "This spot is outside the area RouteMaker covers.";
  if (status === 429) return "Too many look-ups at once; wait a moment and try again.";
  return "The road information is not available right now; try again shortly.";
}

/** Ask the API about a spot. */
export async function fetchSegmentInfo(
  origin: string,
  point: LonLat,
  signal?: AbortSignal,
  fresh = false,
  trail = false,
): Promise<InfoState> {
  try {
    // `fresh` after an edit: the answer is cached for five minutes, and the rider has just changed it.
    const response = await fetch(segmentInfoUrl(origin, point, trail), {
      signal,
      headers: { Accept: "application/json" },
      ...(fresh ? { cache: "reload" as const } : {}),
    });
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
  if (state.kind === "error") return t("Road info");
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

/**
 * The status sentence said again when the spot's federal area changes after the road's answer
 * (a Mass Ride whose federal data comes late; item 239), or null when there is nothing to say
 * again: no request, an answer still loading, or an answer that belongs to an earlier request
 * (`stateFor`, the request `state` was fetched for), whose road must not be said with the new
 * spot's area.
 */
export function refreshedSaid(
  request: InfoRequest | null,
  stateFor: InfoRequest | null,
  state: InfoState,
  federalSaid: string,
  hazardSaid = "",
): string | null {
  if (!request || stateFor !== request || state.kind === "loading") return null;
  return [infoSaid(state), hazardSaid, federalSaid].filter(Boolean).join(" ");
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
