/**
 * The marks for a trip's legs and for transit lines, shared by the trip's option rows and the
 * station popups (Stephen, 2026-10-12): an emoji the eye reads at a glance, and the words a screen
 * reader says instead. The emoji is never the only cue: wherever a mark shows, it is aria-hidden and
 * its spoken words are the accessible text ("🔴" is "Red Line", "🚌C53" is "bus C53").
 *
 * - 🚶 walk, 🚲 a bike (your own or a bikeshare bike)
 * - Metro by its line's colour: 🔴 Red, 🟠 Orange, 🔵 Blue, 🟢 Green, 🟡 Yellow, ⚪ Silver
 * - a bus by its route: "🚌C53"
 * - MARC and VRE by their line: "🚆Penn", "🚆Camden", "🚆Brunswick", "🚆Manassas", "🚆Fredericksburg"
 * - Light RailLink 🚈, Metro SubwayLink 🚇
 *
 * Plain functions with no imports, so the module can be copied or imported anywhere.
 */

export interface Mark {
  /** What shows: "🔴", "🚌C53", "🚆Penn". Always aria-hidden. */
  mark: string;
  /** What a screen reader says instead: "Red Line", "bus C53", "MARC Penn Line". */
  spoken: string;
}

export const WALK_MARK: Mark = { mark: "🚶", spoken: "walk" };
export const BIKE_MARK: Mark = { mark: "🚲", spoken: "bike" };
export const BIKESHARE_MARK: Mark = { mark: "🚲", spoken: "bikeshare" };

/** Metro's lines by colour, keyed by the line's colour word ("Red Line" and "Red" both find it). */
export const METRO_LINE_MARKS: Readonly<Record<string, string>> = {
  Red: "🔴",
  Orange: "🟠",
  Blue: "🔵",
  Green: "🟢",
  Yellow: "🟡",
  Silver: "⚪",
};

const TRAIN = "🚆";
const BUS = "🚌";
const LIGHT_RAIL = "🚈";
const SUBWAY = "🚇";

/** A transit system, as the API names it ("Metro", "MARC", "VRE") or by its id ("wmata-rail"). */
type SystemKind = "metro" | "bus" | "rail" | "light-rail" | "subway";

const SYSTEM_KINDS: Readonly<Record<string, SystemKind>> = {
  metro: "metro",
  "wmata-rail": "metro",
  metrobus: "bus",
  "wmata-bus": "bus",
  bus: "bus",
  marc: "rail",
  vre: "rail",
  "light raillink": "light-rail",
  "mta-light-rail": "light-rail",
  "metro subwaylink": "subway",
  "mta-metro": "subway",
};

/** A system's kind from its mode ("metro", "rail", "bus", ...) or, failing that, its name or id. */
function kindOf(system: string | null | undefined, mode?: string | null): SystemKind | null {
  if (mode === "metro" || mode === "bus" || mode === "rail" || mode === "light-rail" || mode === "subway") return mode;
  return SYSTEM_KINDS[(system ?? "").trim().toLowerCase()] ?? null;
}

/** "Red Line" -> "Red"; "Penn Line" -> "Penn". */
function bareLine(line: string): string {
  return line.replace(/\s+line$/i, "").trim();
}

/** "Red" -> "Red Line"; "Red Line" stays. */
function lineWords(line: string): string {
  const bare = bareLine(line);
  return bare ? `${bare} Line` : line;
}

/**
 * One transit line's mark: Metro "Red Line" -> 🔴 "Red Line"; bus "C53" -> "🚌C53" "bus C53"; MARC
 * "Penn Line" -> "🚆Penn" "MARC Penn Line"; Light RailLink 🚈; Metro SubwayLink 🚇.
 */
export function lineMark(system: string | null | undefined, line: string, mode?: string | null): Mark {
  const kind = kindOf(system, mode);
  const name = (system ?? "").trim();
  switch (kind) {
    case "metro": {
      const colour = METRO_LINE_MARKS[bareLine(line)];
      return colour ? { mark: colour, spoken: lineWords(line) } : { mark: SUBWAY, spoken: line ? `${name || "Metro"} ${line}` : name || "Metro" };
    }
    case "bus":
      return { mark: `${BUS}${line}`, spoken: line ? `bus ${line}` : "bus" };
    case "rail": {
      const bare = bareLine(line);
      return { mark: `${TRAIN}${bare}`, spoken: [name, bare ? lineWords(line) : ""].filter(Boolean).join(" ") || "train" };
    }
    case "light-rail":
      return { mark: LIGHT_RAIL, spoken: name || "Light RailLink" };
    case "subway":
      return { mark: SUBWAY, spoken: name || "Metro SubwayLink" };
    default:
      return { mark: TRAIN, spoken: [name, line].filter(Boolean).join(" ") || "train" };
  }
}

/**
 * Several lines that serve the same leg ("Orange Line or Silver Line"): the marks side by side
 * ("🟠⚪", "🚌C51/C53"), the words joined by "or".
 */
export function linesMark(system: string | null | undefined, lines: readonly string[], mode?: string | null): Mark {
  if (lines.length === 0) return lineMark(system, "", mode);
  const marks = lines.map((line) => lineMark(system, line, mode));
  const kind = kindOf(system, mode);
  // A bus's routes share one 🚌; the other single-mark systems (light rail, SubwayLink) show it once.
  const mark =
    kind === "bus"
      ? `${BUS}${lines.join("/")}`
      : kind === "light-rail" || kind === "subway"
        ? marks[0].mark
        : marks.map((m) => m.mark).join("");
  const spoken = kind === "bus" ? `bus ${lines.join(" or ")}` : [...new Set(marks.map((m) => m.spoken))].join(" or ");
  return { mark, spoken };
}

/** One leg of a trip as the API lists it under each option (core.transit `option_legs`). */
export interface TripLeg {
  /** "walk", "ride" (your own bike), "bikeshare", or a transit mode ("metro", "rail", "bus", ...). */
  mode: string;
  minutes: number;
  /** A transit leg's system by name: "Metro", "MARC". */
  system?: string | null;
  /** A transit leg's lines or routes: ["Red Line"], ["C53"]. */
  lines?: readonly string[];
}

export function legMark(leg: TripLeg): Mark {
  switch (leg.mode) {
    case "walk":
      return WALK_MARK;
    case "ride":
      return BIKE_MARK;
    case "bikeshare":
      return BIKESHARE_MARK;
    default:
      return linesMark(leg.system, leg.lines ?? [], leg.mode);
  }
}

/** The legs as they show: "🚶 4 min · 🚲 12 min · 🔴 18 min". aria-hidden: say `legsSaid` instead. */
export function legsText(legs: readonly TripLeg[]): string {
  return legs.map((leg) => `${legMark(leg).mark} ${leg.minutes} min`).join(" · ");
}

/** The legs in words: "walk 4 minutes, bikeshare 12 minutes, Red Line 18 minutes". */
export function legsSaid(legs: readonly TripLeg[]): string {
  return legs.map((leg) => `${legMark(leg).spoken} ${leg.minutes} ${leg.minutes === 1 ? "minute" : "minutes"}`).join(", ");
}
