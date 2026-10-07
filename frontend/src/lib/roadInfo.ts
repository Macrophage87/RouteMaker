/**
 * The map's road panel (OWNER-DECISIONS 441, 441a): a right-click on a computer, a long
 * press on a phone, or the keyboard's way to the road at the map's centre (the
 * "Road info" button on the map, or I with the map focused) opens a dialog of what
 * RouteMaker knows of the nearest road or path (GET /api/segment-info; core.segment_info)
 * with an "Open Street View here" link. Read only: changing a road's stress is a later
 * release (441g-441l).
 *
 * The pure half: the request, the Street View link, which sections show, what the live
 * region says, and the long press's own timing. RoadInfoDialog.tsx draws it; MapView.tsx
 * listens for the gestures.
 */
import type { LonLat } from "./geo.ts";
import { formatRadius } from "./format.ts";

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

export interface SegmentInfo {
  found: boolean;
  title: string;
  tier: number | null;
  open: boolean | null;
  osm_way_id: number | null;
  distance_m: number | null;
  sections: InfoSection[];
  attribution: string[];
}

/** Where the panel was asked for: a spot the rider pointed at, or the map's centre by keyboard. */
export type InfoOrigin = "spot" | "centre";

export interface InfoRequest {
  point: LonLat;
  origin: InfoOrigin;
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
export const STREET_VIEW_TEXT = "Open Street View here";
export const STREET_VIEW_NOTE =
  "Opens Google Street View in a new tab; this spot is sent to Google only if you follow the link.";
export const INFO_BUTTON_LABEL = "Road info at map center";
export const INFO_KEY = "i";
export const INFO_HELP =
  "Right-click the map (or press and hold on a phone) for what's known about the road there, with a Street View link. " +
  "With the map focused, press I for the road at the center of the map, or use Road info at map center.";
/** How long a finger must rest, unmoved, for a long press. */
export const LONG_PRESS_MS = 600;
/** How far a finger may drift and still be a long press, not a pan. */
export const LONG_PRESS_SLOP_PX = 10;

/** Google's public Street View link for a spot (no key, no code of theirs in the app). */
export function streetViewUrl([lon, lat]: LonLat): string {
  const fixed = (n: number) => n.toFixed(6);
  return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${fixed(lat)},${fixed(lon)}`;
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

/** Where the spot is, in words, under the heading. */
export function originText(origin: InfoOrigin): string {
  return origin === "centre" ? "The road nearest the center of the map." : "The road nearest the spot you picked.";
}

/** One row, as a sentence for the live region and the row's own reading: "Speed limit: 30 mph, posted (OpenStreetMap)". */
export function rowText(row: InfoRow): string {
  return `${row.label}: ${row.value}${row.source ? ` (source: ${row.source})` : ""}`;
}

/** What the live region says once the answer is in: the name, the stress and the access, briefly. */
export function infoSaid(state: InfoState): string {
  if (state.kind === "loading") return "";
  if (state.kind === "error") return state.message;
  const { info } = state;
  if (!info.found) return `${NO_ROAD}.`;
  const level = info.sections.find((s) => s.id === "stress")?.rows.find((r) => r.label === "Level")?.value;
  const access = info.sections.find((s) => s.id === "access")?.rows[0]?.value;
  return [`Road information: ${info.title}.`, level ? `${level}.` : "", access ? `${access}.` : ""]
    .filter(Boolean)
    .join(" ");
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
