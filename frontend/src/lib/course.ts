/**
 * A route compiled into a course for a bike computer: the line, its elevations and its turn cues, fitted to a
 * device profile (lib/deviceProfiles.ts), for the FIT (lib/fit.ts) and TCX (lib/tcx.ts) writers. PLAN.md, Import
 * and export: "Every export starts from one compiled route", "FIT course with course points pinned to the nearest
 * record; TCX".
 *
 * Nothing new is computed about the route here. The line and its elevations are the GPX export's
 * (gpxText.ts, elevationsAlong); the cues are Ride mode's (navigate.ts, rideModel): a turn is the turn and the
 * street, as the Ride cues say it, and hazards, walks, stops and the end are theirs too. Each cue is pinned to
 * the record nearest it along the line.
 *
 * Fitting to a profile: cues over its budget are dropped lowest priority first (notes on busier, calmer or unpaved
 * stretches, then flagged junctions, then turns onto unnamed ways, then the rest), and the start, the finish, the
 * stops and the Avoid and work-zone warnings are never dropped (PLAN.md: "danger-type cues are never dropped;
 * where protected cues alone exceed a profile's budget the export warns and offers a split"). So only those
 * warnings are danger cues: a flagged crossing, which can be dropped, is a note. Points over its budget, or a file
 * over its byte budget, are thinned by Douglas-Peucker at the smallest of a few fixed tolerances that fits (larger
 * ones after them for the bytes), never moving a cue's record. What was trimmed is said in one line (courseLine).
 *
 * Privacy: the plan's own points are named by role only, Start, Stop N and Finish, never by a saved place's label
 * (a Home is "Start" or "Finish" in the file). Times are the route's own moving time from a fixed base, never the
 * clock, so one route always gives the same bytes (PLAN.md, Clean exports).
 */
import type { RouteResponse } from "./api.ts";
import type { DeviceProfile } from "./deviceProfiles.ts";
import { formatDistance, formatFeet, formatMilesCapped } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { COPYRIGHT_AUTHOR, CREATOR } from "./gpx.ts";
import { elevationsAlong, exportFileName, exportName } from "./gpxText.ts";
import { writeFit } from "./fit.ts";
import { writeTcx } from "./tcx.ts";
import { rideModel, turnWords, type Cue } from "./navigate.ts";
import { presetSaid } from "./presets.ts";

export type CourseFormat = "fit" | "tcx";

/**
 * The canonical cue types a course carries (PLAN.md's cue model, as far as the turn model produces it today:
 * left, right and a bear as slight left or right; no sharp, fork or u-turn).
 */
export type CourseCueType = "start" | "finish" | "stop" | "left" | "right" | "slight_left" | "slight_right" | "danger" | "walk" | "note";

const TURN_TYPES = { left: "left", right: "right", bear_left: "slight_left", bear_right: "slight_right" } as const;
const TURN_NAMES = { left: "Left", right: "Right", slight_left: "Bear left", slight_right: "Bear right" } as const;

export interface CourseCue {
  type: CourseCueType;
  /** The record it is pinned to. */
  vertex: number;
  /** A short name for the unit's screen, within the profile's (and the format's) limit. */
  name: string;
  /** The cue in full, as Ride says it ("Left onto R Street Northwest."). */
  text: string;
}

export interface CourseRecord {
  lon: number;
  lat: number;
  /** Metres above sea level, or null where the route's profile has none. */
  ele: number | null;
  /** Metres along the line, as the route was planned (thinning keeps each record's own). */
  distM: number;
  /** Seconds from the course's start at the route's planned pace. */
  timeS: number;
}

export interface CourseTrim {
  profile: DeviceProfile;
  cuesBefore: number;
  cuesKept: number;
  /** Cues the course must keep (start, finish, stops, Avoid and work-zone warnings). */
  protectedCues: number;
  /** More of those than the budget: nothing is dropped (the turns are kept too) and the line says to split. */
  protectedOver: boolean;
  pointsBefore: number;
  pointsKept: number;
  /** The thinning tolerance used, in metres, or 0 where the line was not thinned. */
  toleranceM: number;
  /** The written file's size in bytes. */
  bytes: number;
}

export interface Course {
  format: CourseFormat;
  /** The course's name, within the profile's (and the format's) limit. */
  name: string;
  /** The route's credits and what it is, for TCX's Course/Notes. */
  notes: string;
  records: CourseRecord[];
  cues: CourseCue[];
  /** Seconds since 1970 of the first record: a fixed base, never the clock. */
  baseUnixS: number;
  totalM: number;
  totalS: number;
  climbM: number;
  descentM: number;
  trim: CourseTrim;
}

/** 2000-01-01T00:00:00Z: every course starts here, so the bytes never depend on the clock. */
export const COURSE_BASE_UNIX_S = 946_684_800;
/** TCX's own caps (TrainingCenterDatabase v2: RestrictedToken_t 15, CoursePointName_t 10). */
export const TCX_COURSE_NAME_CHARS = 15;
export const TCX_CUE_NAME_CHARS = 10;
/** Douglas-Peucker tolerances tried in turn, in metres: the smallest that fits the profile is used. */
export const THIN_TOLERANCES_M = [1, 2, 5, 10] as const;
/** Tried after those only while the file is over the profile's byte budget, doubling up to this. */
const SIZE_TOLERANCE_MAX_M = 10_240;
/** The pace used where the route has no moving time: about 11 mph (5 m/s). */
const FALLBACK_PACE_MS = 5;
/** Never dropped, whatever the budget. */
const PROTECTED = Number.POSITIVE_INFINITY;
/**
 * The course name's credit where it fits (PLAN.md: FIT "carries attribution in the course name suffix"). Plain
 * ASCII: a unit's font may have no ©.
 */
export const FIT_NAME_CREDIT = " (c) OSM";

type CompiledRoute = Pick<RouteResponse, "preset" | "distance_m" | "duration_s" | "climb_m" | "descent_m" | "geometry" | "attribution"> &
  Partial<RouteResponse>;

const STREET_WORDS: Record<string, string> = {
  street: "St", avenue: "Ave", road: "Rd", drive: "Dr", boulevard: "Blvd", parkway: "Pkwy", place: "Pl",
  court: "Ct", lane: "Ln", terrace: "Ter", trail: "Trl", highway: "Hwy", circle: "Cir", square: "Sq",
  northwest: "NW", northeast: "NE", southwest: "SW", southeast: "SE", bridge: "Br", path: "Path",
};

/** "R Street Northwest" as a unit's screen has room for it: "R St NW". */
export function abbreviateStreet(street: string): string {
  return street
    .trim()
    .split(/\s+/)
    .map((word) => STREET_WORDS[word.toLowerCase()] ?? word)
    .join(" ");
}

/** The first `chars` characters (by code point), without a trailing space. */
export function clip(text: string, chars: number): string {
  return Array.from(text).slice(0, chars).join("").trimEnd();
}

function named(street: string | null): string | null {
  if (!street) return null;
  const s = street.trim();
  return s && !/^unnamed\b/i.test(s) ? s : null;
}

/** A cue's kind, short name and how much it matters, from Ride's cue. */
function fromRide(cue: Cue): { type: CourseCueType; name: string; priority: number } | null {
  const street = named(cue.street);
  switch (cue.kind) {
    case "turn": {
      const turn = TURN_TYPES[cue.movement ?? "right"];
      return { type: turn, name: street ? abbreviateStreet(street) : TURN_NAMES[turn], priority: street ? 4 : 3 };
    }
    case "onto":
      return { type: "note", name: street ? abbreviateStreet(street) : "Continue", priority: 1 };
    case "walk":
      return { type: "walk", name: "Walk bike", priority: 4 };
    case "hazard": {
      // An Avoid-rated junction or a work zone is a danger cue and kept; a flagged crossing can go before a turn,
      // so it is a note: a danger cue is never dropped (PLAN.md).
      const kept = cue.source === "avoid" || cue.source === "workzone";
      const name = street ? abbreviateStreet(street) : "Caution";
      return kept ? { type: "danger", name, priority: PROTECTED } : { type: "note", name, priority: cue.severity === "red" ? 2 : 1 };
    }
    case "busy":
      return { type: "note", name: "Busy road", priority: 0 };
    case "calmer":
      return { type: "note", name: "Calmer", priority: 0 };
    case "unpaved":
      return { type: "note", name: "Unpaved", priority: 0 };
    case "stop":
      return { type: "stop", name: `Stop ${cue.stop ?? ""}`.trim(), priority: PROTECTED };
    case "end":
      return { type: "finish", name: "Finish", priority: PROTECTED };
  }
}

/** The index of the vertex nearest `m` metres along. */
function nearestVertex(along: readonly number[], m: number): number {
  let lo = 0;
  let hi = along.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (along[mid] < m) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && m - along[lo - 1] < along[lo] - m ? lo - 1 : lo;
}

/** Distance in metres from `p` to the segment a-b, on a local flat projection (small spans only). */
function offsetM(p: LonLat, a: LonLat, b: LonLat): number {
  const kx = 111_320 * Math.cos((a[1] * Math.PI) / 180);
  const ky = 110_574;
  const [px, py] = [(p[0] - a[0]) * kx, (p[1] - a[1]) * ky];
  const [bx, by] = [(b[0] - a[0]) * kx, (b[1] - a[1]) * ky];
  const len = bx * bx + by * by;
  const t = len > 0 ? Math.max(0, Math.min(1, (px * bx + py * by) / len)) : 0;
  return Math.hypot(px - t * bx, py - t * by);
}

/**
 * Which vertices Douglas-Peucker keeps at `toleranceM`, the `keep` ones always: no dropped vertex lies further than
 * the tolerance from the thinned line, so the line never leaves the way by more.
 */
export function thin(line: readonly LonLat[], toleranceM: number, keep: ReadonlySet<number> = new Set()): boolean[] {
  const kept = line.map((_, i) => i === 0 || i === line.length - 1 || keep.has(i));
  const anchors = kept.flatMap((k, i) => (k ? [i] : []));
  for (let a = 1; a < anchors.length; a += 1) {
    const stack: [number, number][] = [[anchors[a - 1], anchors[a]]];
    while (stack.length) {
      const [from, to] = stack.pop() as [number, number];
      let worst = -1;
      let worstM = toleranceM;
      for (let i = from + 1; i < to; i += 1) {
        const d = offsetM(line[i], line[from], line[to]);
        if (d > worstM) {
          worst = i;
          worstM = d;
        }
      }
      if (worst > 0) {
        kept[worst] = true;
        stack.push([from, worst], [worst, to]);
      }
    }
  }
  return kept;
}

/**
 * The course's name: for FIT, the longest wording that fits with the credit after it; otherwise (and for TCX) the
 * longest wording that fits alone.
 */
export function courseName(route: Pick<RouteResponse, "preset" | "distance_m">, chars: number, format: CourseFormat): string {
  const ride = presetSaid(route.preset);
  const miles = formatMilesCapped(route.distance_m);
  const options = [exportName(route), `${ride} ${formatDistance(route.distance_m)}`, `${ride} ${miles}`, formatDistance(route.distance_m), `${miles} route`];
  const fits = (text: string) => Array.from(text).length <= chars;
  const credited = format === "fit" ? options.find((o) => fits(o + FIT_NAME_CREDIT)) : undefined;
  if (credited) return credited + FIT_NAME_CREDIT;
  return options.find(fits) ?? clip(options[options.length - 1], chars);
}

/** The route's credits as the GPX export words them (gpx.ts writeGpx). */
export function creditLine(attribution: readonly string[]): string {
  const credit = attribution.length ? attribution.join("; ") : `© ${COPYRIGHT_AUTHOR}, ODbL`;
  return `Route data: ${credit}.`;
}

/** A cue as every export reads it: Ride's, with its kind, its short name before any device's limit, and where it is. */
export interface RouteCue {
  type: CourseCueType;
  name: string;
  /** Ride's words in full. */
  text: string;
  /** Metres along the line (the finish's is the line's length). */
  atM: number;
  /** The street the cue turns onto or is on, or null where unnamed; for the start, the first stretch's. */
  street: string | null;
  priority: number;
  /** Ride's cue kind, and for a hazard the description entry it came from (avoid, workzone, junction...). */
  kind: Cue["kind"] | "start";
  source?: string;
  /** A jog's second turn (Ride's `joined`): a course point of its own, but no row of the cue sheet, the first's text saying it. */
  joined?: boolean;
  /** A jog's first turn: its own turn alone ("Right onto 6th Street Northwest."), for a course point's notes, `text` saying both. */
  turnText?: string;
}

/**
 * Ride's cues for the route, in order, with the start first: the one list the FIT and TCX courses and the PDF cue
 * sheets (cueSheetPdf.ts) are made from. `vias` are the plan's via points by index, which are not cues, as in Ride.
 */
export function routeCues(route: CompiledRoute, vias: readonly number[] = []): RouteCue[] {
  const model = rideModel(route as RouteResponse, vias);
  const all: RouteCue[] = [{ type: "start", name: "Start", text: "Start.", atM: 0, street: named(model.stretches[0]?.street ?? null), priority: PROTECTED, kind: "start" }];
  for (const cue of model.cues) {
    const made = fromRide(cue);
    if (!made) continue;
    const atM = cue.kind === "end" ? model.lengthM : cue.atM;
    all.push({
      type: made.type,
      name: made.name,
      text: cue.text,
      atM,
      street: named(cue.street),
      priority: made.priority,
      kind: cue.kind,
      ...(cue.source ? { source: cue.source } : {}),
      ...(cue.joined ? { joined: true } : {}),
      ...(cue.then && cue.movement ? { turnText: turnWords(cue.movement, cue.street) } : {}),
    });
  }
  return all;
}

/**
 * The route shown as a course for `profile`. `vias` are the plan's via points by index (pointKinds.ts), which are
 * not cues, as in Ride.
 */
export function compileCourse(route: CompiledRoute, profile: DeviceProfile, format: CourseFormat, vias: readonly number[] = []): Course {
  const line = route.geometry.coordinates;
  const along: number[] = [0];
  for (let i = 1; i < line.length; i += 1) along.push(along[i - 1] + haversineM(line[i - 1], line[i]));
  const lineM = along[along.length - 1] ?? 0;
  const elevations = elevationsAlong(line, route.profile);
  const totalS = route.duration_s > 0 ? route.duration_s : lineM / FALLBACK_PACE_MS;
  const timeAt = (m: number) => (lineM > 0 ? (m / lineM) * totalS : 0);

  // The cues, Ride's, in order, with the start first.
  const nameChars = format === "tcx" ? Math.min(TCX_CUE_NAME_CHARS, profile.cueNameChars) : profile.cueNameChars;
  const all: (CourseCue & { priority: number })[] = routeCues(route, vias).map((cue) => ({
    type: cue.type,
    vertex: cue.type === "start" ? 0 : cue.type === "finish" ? line.length - 1 : nearestVertex(along, cue.atM),
    name: clip(cue.name, nameChars),
    // A course point is one turn: a jog's second is a point of its own, so the first's notes are its own turn.
    text: cue.turnText ?? cue.text,
    priority: cue.priority,
  }));

  // Over the budget: the least important first, and of those the one nearest the cue before it. Where the cues
  // that must be kept pass it by themselves, nothing is dropped: giving up every turn would still not make the
  // course fit, so the rider is told to split it instead.
  const dropped = new Set<number>();
  const protectedCount = all.filter((c) => c.priority === PROTECTED).length;
  const room = profile.maxCues;
  if (all.length > room && protectedCount <= room) {
    const order = all
      .map((c, i) => ({ i, priority: c.priority, gap: i > 0 ? along[c.vertex] - along[all[i - 1].vertex] : Infinity }))
      .filter((c) => c.priority !== PROTECTED)
      .sort((a, b) => a.priority - b.priority || a.gap - b.gap || a.i - b.i);
    for (const c of order.slice(0, all.length - room)) dropped.add(c.i);
  }
  const cues = all.filter((_, i) => !dropped.has(i)).map(({ priority: _priority, ...cue }) => cue);

  const courseChars = format === "tcx" ? Math.min(TCX_COURSE_NAME_CHARS, profile.courseNameChars) : profile.courseNameChars;
  const name = courseName(route, courseChars, format);
  const notes = `${exportName(route)}. ${creditLine(route.attribution)} Planned with ${CREATOR}.`;
  const build = (keep: readonly boolean[], toleranceM: number): Course => {
    const index = new Map<number, number>();
    const records: CourseRecord[] = [];
    line.forEach(([lon, lat], i) => {
      if (!keep[i]) return;
      index.set(i, records.length);
      const ele = elevations[i];
      records.push({ lon, lat, ele: typeof ele === "number" && Number.isFinite(ele) ? ele : null, distM: along[i], timeS: timeAt(along[i]) });
    });
    return {
      format,
      name,
      notes,
      records,
      cues: cues.map((c) => ({ ...c, vertex: index.get(c.vertex) ?? 0 })),
      baseUnixS: COURSE_BASE_UNIX_S,
      totalM: lineM,
      totalS,
      climbM: route.climb_m,
      descentM: route.descent_m,
      trim: {
        profile,
        cuesBefore: all.length,
        cuesKept: cues.length,
        protectedCues: protectedCount,
        protectedOver: protectedCount > profile.maxCues,
        pointsBefore: line.length,
        pointsKept: records.length,
        toleranceM,
        bytes: 0,
      },
    };
  };
  const sized = (course: Course): Course => {
    course.trim.bytes = format === "fit" ? writeFit(course).length : UTF8.encode(writeTcx(course)).length;
    return course;
  };
  const fits = (course: Course) => course.records.length <= profile.maxPoints && sized(course).trim.bytes <= profile.maxBytes;

  // Over the point or byte budget: thinned at the smallest tolerance that fits, the cues' records always kept.
  // Past the point budget's largest tolerance, only the bytes go on thinning it (doubling); a course still over
  // the point budget there stays at that tolerance, and the line says so.
  const pointsLast = THIN_TOLERANCES_M[THIN_TOLERANCES_M.length - 1];
  let course = build(line.map(() => true), 0);
  if (!fits(course)) {
    const pinned = new Set(cues.map((c) => c.vertex));
    const tolerances: number[] = [...THIN_TOLERANCES_M];
    for (let t = pointsLast * 2; t <= SIZE_TOLERANCE_MAX_M; t *= 2) tolerances.push(t);
    for (const t of tolerances) {
      course = build(thin(line, t, pinned), t);
      if (fits(course) || (t >= pointsLast && course.records.length > profile.maxPoints)) break;
    }
  }
  return course.trim.bytes > 0 ? course : sized(course);
}

const UTF8 = new TextEncoder();

const count = (n: number) => n.toLocaleString("en-US");
const megabytes = (bytes: number) => (bytes >= 1_000_000 ? `${Number((bytes / 1_000_000).toFixed(1))} MB` : `${Math.ceil(bytes / 1000)} KB`);

/**
 * What the export did to fit the device, in one short line for the GPX section's status: "FIT course for Garmin
 * Edge: all 42 cues and 3,120 points fit.", or what was left out, or the warning that the cues the course must keep
 * are more than the device shows.
 */
export function courseLine(course: Pick<Course, "format" | "trim">): string {
  const { profile, cuesBefore, cuesKept, protectedCues, protectedOver, pointsBefore, pointsKept, toleranceM } = course.trim;
  const head = `${course.format.toUpperCase()} course for ${profile.label}`;
  if (protectedOver) {
    return `${head}: ${count(protectedCues)} of its cues must be kept, more than the ${count(profile.maxCues)} the device shows; split the route in two.`;
  }
  const parts: string[] = [];
  if (cuesKept < cuesBefore) parts.push(`kept ${count(cuesKept)} of ${count(cuesBefore)} cues, least important left out`);
  if (pointsKept < pointsBefore) {
    parts.push(
      pointsKept > profile.maxPoints
        ? `thinned to ${count(pointsKept)} points, still more than the ${count(profile.maxPoints)} it takes`
        : `thinned from ${count(pointsBefore)} to ${count(pointsKept)} points, within ${formatFeet(toleranceM)} of the route`,
    );
  }
  if (course.trim.bytes > profile.maxBytes) parts.push(`still larger than the ${megabytes(profile.maxBytes)} it takes`);
  if (!parts.length) return `${head}: all ${count(cuesKept)} cues and ${count(pointsKept)} points fit.`;
  return `${head}: ${parts.join("; ")}.`;
}

/** The file's name: the GPX export's (gpxText.ts exportFileName), with the format's extension. */
export function courseFileName(route: Pick<RouteResponse, "preset" | "distance_m">, format: CourseFormat): string {
  return exportFileName(route).replace(/\.gpx$/, `.${format}`);
}
