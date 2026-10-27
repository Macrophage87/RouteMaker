/**
 * Via points and stops (v0.7.0 plan, "Via points vs stops"; Stephen 2026-10-14: "let's make a distinction
 * between waypoints (via points) that are mostly about adjusting the route to our preferences and actual stops").
 *
 * - A via point only shapes the route: a small hollow marker with no number, never announced, not listed as a
 *   stop, not a <wpt> in GPX, sent to the router as a point it passes without a U-turn or a stop.
 * - A stop is a real stop: numbered, announced, listed, a <wpt>, a "break" for the router.
 *
 * Defaults, so nobody has to choose: dragging the route line or tapping the map makes a via point; a searched
 * place, a chip (Home, Food, Water, Restroom), a Ctrl+click (Cmd+click on a Mac) or the road panel's Add as stop (a
 * long press) makes a stop. The point's menu switches them. A file's named points are stops, its unnamed ones vias.
 *
 * Stephen 2026-10-24: "via points the default", a stop asks for a name, a re-route treats "via points as guides and
 * stops as mandatory" (lib/navigate.ts replanKept), and stops show on the map while riding. A stop's own name, the
 * one the rider typed (or a file gave it), is kept on its pair as its kind is (`named`, `nameOf`).
 *
 * How a point's kind is kept: the plan's points are immutable [lon, lat] pairs, and the history (undo, redo,
 * Reset) keeps the same pair objects, so a kind is kept on the pair itself, by identity, in a WeakSet. A pair's
 * kind is set when it is made and never changed: switching a point's kind puts a new pair in its place
 * (`withKind`), so the switch is an edit that Undo takes back like any other. Moving a point keeps its kind
 * (`moved`). Only the points between the start and the end have a kind that matters; the ends are neither.
 */
import { addPoint, type LonLat } from "./geo.ts";
import { LOOP_START_NAME } from "./summary.ts";
import { t } from "./i18n.ts";

export type PointKind = "stop" | "via";

/** The marks: which pairs are via points. One for the page (App.tsx); a test makes its own. */
export class ViaMarks {
  private readonly vias = new WeakSet<LonLat>();
  // Plan's manual mode (v0.9.1): the pairs the line to which was drawn, straight, not routed. Kept the same way.
  private readonly drawnTo = new WeakSet<LonLat>();
  // A stop's own name (the rider's, or a file's), on its pair; a via point has none.
  private readonly names = new WeakMap<LonLat, string>();

  /** Whether this pair was made as a via point. */
  isVia = (point: LonLat): boolean => this.vias.has(point);

  /** Whether the leg that ends at this pair was drawn as a straight line (Plan's manual mode). */
  isDrawn = (point: LonLat): boolean => this.drawnTo.has(point);

  /** A stop's own name, or undefined: none given (the map's place name is shown then). */
  nameOf = (point: LonLat): string | undefined => this.names.get(point);

  /** Names a pair just made (trimmed, at most STOP_NAME_MAX; blank is no name), and gives it back. */
  named(point: LonLat, name: string | undefined): LonLat {
    const clean = cleanStopName(name);
    if (clean) this.names.set(point, clean);
    return point;
  }

  /** Marks a pair just made as a via point, and gives it back. */
  via(point: LonLat): LonLat {
    this.vias.add(point);
    return point;
  }

  /** Marks a pair just made as the end of a drawn leg, and gives it back. */
  drawn(point: LonLat): LonLat {
    this.drawnTo.add(point);
    return point;
  }

  /** A new pair at the same place, of `kind` (the point menu's "Make this a stop / a via point"). */
  withKind(point: LonLat, kind: PointKind): LonLat {
    const copy: LonLat = [point[0], point[1]];
    if (this.isDrawn(point)) this.drawn(copy);
    // A stop made a via point and back keeps its name for the round trip; a via point never shows one.
    this.named(copy, this.nameOf(point));
    return kind === "via" ? this.via(copy) : copy;
  }

  /**
   * Names the stop in place (blank takes its name away): only a label changes, so the plan's points stay the same
   * pairs and no new route is asked for.
   */
  rename(point: LonLat, name: string): void {
    const clean = cleanStopName(name);
    if (clean) this.names.set(point, clean);
    else this.names.delete(point);
  }

  /** Names the pairs a link or a saved route names (`names`: index to name), and gives the list back. */
  nameAt<T extends LonLat[]>(points: T, names: ReadonlyMap<number, string>): T {
    for (const [i, name] of names) if (points[i]) this.named(points[i], name);
    return points;
  }

  /** Marks the pairs at `indices` (a link's or a saved route's `via` field) as via points; the list back. */
  markAt<T extends LonLat[]>(points: T, indices: readonly number[]): T {
    for (const i of indices) if (points[i]) this.via(points[i]);
    return points;
  }

  /** Marks the legs at `legs` (a link's `line` field) as drawn: leg i ends at point i + 1. The list back. */
  markDrawn<T extends LonLat[]>(points: T, legs: readonly number[]): T {
    for (const i of legs) if (points[i + 1]) this.drawn(points[i + 1]);
    return points;
  }

  /**
   * `points` with exactly the legs at `legs` drawn: a pair whose mark must change is replaced by a new one at the same
   * place, of the same kind (Reverse, whose legs run the other way). The list back, the same pairs where none changes.
   */
  withLegs(points: readonly LonLat[], legs: readonly number[]): LonLat[] {
    const wanted = new Set(legs);
    return points.map((point, i) => {
      if (i === 0 || wanted.has(i - 1) === this.isDrawn(point)) return point;
      const copy: LonLat = [point[0], point[1]];
      if (this.isVia(point)) this.via(copy);
      this.named(copy, this.nameOf(point));
      return wanted.has(i - 1) ? this.drawn(copy) : copy;
    });
  }

  /**
   * After an edit from `before` to `next` that adds one point (a tap, a stop, a dragged line): the new pair's leg is
   * drawn in manual mode, and otherwise where it splits a drawn leg (the leg on from it is drawn), so both halves stay
   * drawn. Any other edit (a move, a replacement, a new order) changes no mark. `next` back.
   */
  afterEdit<T extends readonly LonLat[]>(before: readonly LonLat[], next: T, manual: boolean): T {
    if (next.length !== before.length + 1) return next;
    const kept = new Set(before);
    next.forEach((point, i) => {
      if (i === 0 || kept.has(point)) return;
      const after = next[i + 1];
      if (manual || (after && this.isDrawn(after))) this.drawn(point);
    });
    return next;
  }

  /** A pair moved to `to` (a dragged marker): the same kind as the one it replaces, its leg drawn as it was. */
  moved(from: LonLat, to: LonLat): LonLat {
    if (this.isDrawn(from)) this.drawn(to);
    this.named(to, this.nameOf(from));
    return this.isVia(from) ? this.via(to) : to;
  }
}

/** The page's marks (App.tsx and the views it renders); a test makes its own. */
export const VIA_MARKS = new ViaMarks();

/** Whether point `index` of `count` is between the start and the end (a loop's last point too). */
export function isMiddle(index: number, count: number, loop: boolean): boolean {
  return index > 0 && (loop ? index < count : index < count - 1);
}

/**
 * The via points' indices, for the route request (`via_points`) and the link: points between the start and the
 * end only. A loop's last point is sent as a stop: the API counts its ends from the points it is sent.
 */
export function viaIndices(points: readonly LonLat[], isVia: (p: LonLat) => boolean): number[] {
  const out: number[] = [];
  for (let i = 1; i < points.length - 1; i += 1) if (isVia(points[i])) out.push(i);
  return out;
}

/**
 * The drawn legs' indices (Plan's manual mode), for the route request (`straight_legs`) and the link (`line`): leg i
 * runs from point i to point i + 1, and is drawn where point i + 1 is marked.
 */
export function drawnLegs(points: readonly LonLat[], isDrawn: (p: LonLat) => boolean = VIA_MARKS.isDrawn): number[] {
  const out: number[] = [];
  for (let i = 1; i < points.length; i += 1) if (isDrawn(points[i])) out.push(i - 1);
  return out;
}

/** Plan's map bar switch for manual mode, and what is said as it turns on and off. */
export const MANUAL_LABEL = t("Manual mode");
export const MANUAL_TITLE = t("Manual mode: each point you tap is joined by a straight line");
export const MANUAL_ON_SAID = t("Manual mode on. Each point you tap is the new end, joined by a straight line.");
export const MANUAL_OFF_SAID = t("Manual mode off. New points are routed.");
/** Said after a point's "added" when the line to it is drawn. */
export const DRAWN_SAID = t("Joined by a straight line.");

/** The link's `line` field read back: the drawn legs between `count` points, in order, each once. */
export function decodeDrawn(value: string | null, count: number): number[] {
  if (!value) return [];
  const out = new Set<number>();
  for (const part of value.split(",")) {
    const i = Number(part);
    if (Number.isInteger(i) && i >= 0 && i < count - 1) out.add(i);
  }
  return [...out].sort((a, b) => a - b);
}

/** A point's kind as the plan uses it: "start", "end", or between them "stop" or "via". */
export type PointRole = "start" | "end" | "stop" | "via";

export interface PointNaming {
  role: PointRole;
  /** "Start", "End", "Stop 2", "Via point". */
  name: string;
  /** A stop's number, counting stops only (via points are not numbered); null otherwise. */
  number: number | null;
}

/** Each point's role and name: stops numbered among themselves, via points unnumbered. */
export function namePoints(points: readonly LonLat[], isVia: (p: LonLat) => boolean, loop = false): PointNaming[] {
  let stops = 0;
  return points.map((point, index) => {
    if (index === 0) return { role: "start", name: loop ? LOOP_START_NAME : "Start", number: null };
    if (!isMiddle(index, points.length, loop)) return { role: "end", name: "End", number: null };
    // A loop's last point is always a stop: the API counts its ends from the points it is sent (viaIndices).
    if (index < points.length - 1 && isVia(point)) return { role: "via", name: "Via point", number: null };
    stops += 1;
    return { role: "stop", name: `Stop ${stops}`, number: stops };
  });
}

/** What a marker or a list row is called by a screen reader: "Via point", "Stop 2, Union Market". */
export function pointSaid(naming: PointNaming, place: string | undefined): string {
  if (naming.role === "via") return place ? `Via point, ${place}` : "Via point";
  return place ? `${naming.name}, ${place}` : naming.name;
}

/** The point menu's switch: what it says for a point of this role, or null on the start and the end. */
export function kindSwitchLabel(role: PointRole): string | null {
  if (role === "via") return "Make this a stop";
  if (role === "stop") return "Make this a via point";
  return null;
}

/** Said once the switch is made. */
export function kindSwitchedSaid(to: PointKind, place: string | undefined): string {
  const where = place ? ` ${place}` : "";
  return to === "via" ? `Via point${where ? `:${where}` : ""}. It shapes the route; no stop there.` : `Stop added back${where ? `:${where}` : ""}.`;
}

/**
 * The stop-order request's points (Best order moves stops only): the start, the stops and the end, without the
 * via points. Each via point stays with the stop it leads to (the next stop or end after it) and moves with it.
 */
export function stopsOnly(points: readonly LonLat[], isVia: (p: LonLat) => boolean, loop = false): { points: LonLat[]; leading: LonLat[][] } {
  const out: LonLat[] = [];
  const leading: LonLat[][] = [];
  let pending: LonLat[] = [];
  points.forEach((point, index) => {
    if (isMiddle(index, points.length, loop) && index < points.length - 1 && isVia(point)) {
      pending.push(point);
      return;
    }
    out.push(point);
    leading.push(pending);
    pending = [];
  });
  // A loop's via points after its last stop lead back to the start: they stay at the end.
  if (pending.length) leading.push(pending);
  return { points: out, leading };
}

/** The whole ride again from a new order of `stopsOnly`'s points: each stop with the via points that lead to it. */
export function withVias(order: readonly number[], split: { points: readonly LonLat[]; leading: readonly LonLat[][] }): LonLat[] {
  const out: LonLat[] = [];
  for (const i of order) out.push(...(split.leading[i] ?? []), split.points[i]);
  // Via points that led back to a loop's start.
  if (split.leading.length > split.points.length) out.push(...split.leading[split.points.length]);
  return out;
}

/** How many stops Best order may move once the via points are left out (Go and Plan show it from two). */
export function movableStops(points: readonly LonLat[], isVia: (p: LonLat) => boolean, loop = false): number {
  return namePoints(points, isVia, loop).filter((n) => n.role === "stop").length;
}

/**
 * A searched place added as a stop while a route has a start and an end (v0.7.0 plan, "Keep adding stops by
 * search"): where it adds the least distance (lib/geo.ts addPoint, the straight-line test the map's added points
 * already use). Its index in the new list, for what is said.
 */
export function addStopWhereShortest(points: readonly LonLat[], point: LonLat, loop = false): { points: LonLat[]; index: number } {
  const next = addPoint(points, point, loop);
  return { points: next, index: next.indexOf(point) };
}

/** Said when Go's "Add a stop" or a chip adds a stop: "Stop 2, Union Market, added. Undo removes it." */
export function stopAddedSaid(points: readonly LonLat[], index: number, isVia: (p: LonLat) => boolean, loop: boolean, place: string): string {
  const name = namePoints(points, isVia, loop)[index]?.name ?? "Stop";
  return `${name}, ${place}, added. Undo removes it.`;
}

/** A via point's name: its markers, list rows and its route point in a GPX file (lib/gpx.ts planPointNames). */
export const VIA_POINT_NAME = t("Via point");

/** The link's field for the via points: "1,3", or null with none. Old links have none: every point is a stop. */
export function encodeVias(points: readonly LonLat[], isVia: (p: LonLat) => boolean): string | null {
  const vias = viaIndices(points, isVia);
  return vias.length ? vias.join(",") : null;
}

/** A marker's label: its visible text (a stop's number; none otherwise), its spoken name, and its pin's style. */
export interface MarkerLabel {
  text: string;
  name: string;
  /** "via" is a numbered stop's pin (its older name); "through" is a via point's small hollow ring. */
  kind: "start" | "end" | "via" | "through";
}

/** Each marker's label (MapView): a via point is a hollow ring with no number, named "Via point". */
export function markerLabels(points: readonly LonLat[], isVia: (p: LonLat) => boolean, loop = false): MarkerLabel[] {
  return namePoints(points, isVia, loop).map((n): MarkerLabel => {
    if (n.role === "start" || n.role === "end") return { text: "", name: n.name, kind: n.role };
    if (n.role === "via") return { text: "", name: n.name, kind: "through" };
    return { text: String(n.number), name: n.name, kind: "via" };
  });
}

/** Said when a point is added or removed, by its name in `points` ("Via point added.", "Stop 2 removed."). */
export function kindSaid(
  points: readonly LonLat[],
  index: number,
  isVia: (p: LonLat) => boolean,
  loop: boolean,
  what: "added" | "removed",
): string {
  return `${namePoints(points, isVia, loop)[index]?.name ?? "Point"} ${what}.`;
}

/** The via indices a link names, those that fit a plan of `count` points (between its ends). */
export function decodeVias(value: string | null, count: number): number[] {
  if (!value) return [];
  const out = new Set<number>();
  for (const part of value.split(",")) {
    const i = Number(part);
    if (Number.isInteger(i) && i > 0 && i < count - 1) out.add(i);
  }
  return [...out].sort((a, b) => a - b);
}

// ---- A stop's own name (Stephen 2026-10-24: a new stop "should also ask for a name") ----------------------

/** The longest name a stop keeps: a street sign's worth, so it fits a marker and a cue. */
export const STOP_NAME_MAX = 40;

/** A name as kept: spaces squeezed, trimmed, at most STOP_NAME_MAX; undefined when nothing is left. */
export function cleanStopName(name: string | undefined | null): string | undefined {
  const clean = (name ?? "").replace(/\s+/g, " ").trim().slice(0, STOP_NAME_MAX).trim();
  return clean || undefined;
}

/**
 * The stops' own names by index, for a link and a saved route (`sn`): stops between the ends only, a loop's last
 * point included (it is a stop: namePoints).
 */
export function stopNames(points: readonly LonLat[], nameOf: (p: LonLat) => string | undefined, isVia: (p: LonLat) => boolean, loop = false): Map<number, string> {
  const out = new Map<number, string>();
  points.forEach((point, i) => {
    const name = nameOf(point);
    const last = i === points.length - 1;
    if (name && isMiddle(i, points.length, loop) && (last || !isVia(point))) out.set(i, name);
  });
  return out;
}

/** The link's `sn` values: "2:Union Market", one per named stop. */
export function encodeStopNames(names: ReadonlyMap<number, string>): string[] {
  return [...names].sort(([a], [b]) => a - b).map(([i, name]) => `${i}:${name}`);
}

/** The `sn` values read back: the names of points that fit a plan of `count` points (after its start; a loop's last is a stop). */
export function decodeStopNames(values: readonly string[], count: number): Map<number, string> {
  const out = new Map<number, string>();
  for (const value of values) {
    const at = value.indexOf(":");
    const i = Number(value.slice(0, at));
    const name = cleanStopName(value.slice(at + 1));
    if (at > 0 && Number.isInteger(i) && i > 0 && i < count && name) out.set(i, name);
  }
  return out;
}

/** Said once a stop is named, or its name taken away. */
export function stopNamedSaid(name: string | undefined): string {
  return name ? `Stop named ${name}.` : "Stop name removed.";
}

/** The name dialog's words (StopNameDialog.tsx). */
export const STOP_NAME_HEADING = t("Name this stop");
export const STOP_NAME_LABEL = t("Name (optional)");
export const STOP_NAME_ADD = t("Add stop");
export const STOP_NAME_SAVE = t("Save name");
export const STOP_NAME_CANCEL = "Cancel";

/** A point menu's way to name or rename a stop. */
export function renameLabel(named: boolean): string {
  return named ? "Rename stop" : "Name this stop";
}

/** A stop drawn on the ride's map (2026-10-24: "Stops should appear on the map when riding"). */
export interface RideStopMark {
  point: LonLat;
  /** The stop's number among the stops. */
  number: number;
  /** Its own name, else the map's name for the spot; undefined with neither. */
  name?: string;
}

/** What a ride stop's marker shows and says: "2" and "Stop 2, Union Market". */
export function rideStopLabel(stop: RideStopMark): { text: string; said: string } {
  return { text: String(stop.number), said: stop.name ? `Stop ${stop.number}, ${stop.name}` : `Stop ${stop.number}` };
}

/**
 * An opened file's points, by Stephen's rule (2026-10-24: "When importing any waypoint without a name is a via, any
 * with one is assumed to be a stop"): between the ends, a point with no name (or a RouteMaker file's "Via point") is a
 * via point, and a named one a stop, its name its own unless it only says its role ("Stop 2", "Start"). A track's
 * points, which have no names, are via points.
 */
export function importedKinds(names: ReadonlyArray<string | undefined> | undefined, count: number): { vias: number[]; names: Map<number, string> } {
  const vias: number[] = [];
  const own = new Map<number, string>();
  for (let i = 1; i < count - 1; i += 1) {
    const name = cleanStopName(names?.[i]);
    if (!name || name === VIA_POINT_NAME || VIA_ROLE_NAME.test(name)) vias.push(i);
    else if (!ROLE_NAME.test(name)) own.set(i, name);
  }
  return { vias, names: own };
}

/** A name that only says a point's role, as a file of ours (or an older one) names its points. */
const ROLE_NAME = new RegExp(`^(?:Start|End|${LOOP_START_NAME}|(?:Stop|Point) \\d+)$`);
/** An older file's name for a via point ("Via 3"; lib/gpxEdit.ts isRoleName). */
const VIA_ROLE_NAME = /^Via \d+$/;

/** The tips' sentence on what a click makes (lib/pointText.ts editingTips). */
export const CLICK_KINDS_TIP = t("A click adds a via point; Ctrl+click (Cmd+click on a Mac) adds a named stop.");
