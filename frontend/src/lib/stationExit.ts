/**
 * Which way out of a Metro station (Stephen, 2026-11-08: leaving the station, "the cue should mention which exit to
 * use"). A walk after a train starts at the entrance the API chose (core/transit.py _nearest_entrance); DC's Metro
 * entrances (rail-data/metro-entrances.geojson, DC open data, public domain) say where each comes up, in
 * `EXIT_TO_ST`: "NE CORNER OF ABLEMARLE STREET NW AND WISCONSIN AVENUE NW". Here that becomes a short sentence in
 * the rider's language: "Take the exit at Albemarle Street NW and Wisconsin Avenue NW." The street names stay as
 * they are, as everywhere in the app.
 */
import type { LonLat } from "./geo.ts";
import { haversineM } from "./geo.ts";
import { t } from "./i18n.ts";

/** An entrance and where it comes up, as DC words it. */
export interface StationExit {
  point: LonLat;
  to: string;
}

/** The walk's start is this near an entrance for it to be that one. Our default. */
export const EXIT_NEAR_M = 60;

// Where along the street the entrance is, which the sentence leaves out: "NE CORNER OF", "WEST SIDE OF", "SW OF".
const WHERE =
  /^(?:(?:N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST|NORTHEAST|NORTHWEST|SOUTHEAST|SOUTHWEST|NORTHEN|NORTHERN|SOUTHERN|EASTERN|WESTERN)\s+(?:(?:CORNER|SIDE)\s+)?OF|INTERSECTION\s+OF|BY|THE\s+CLOSEST\s+EXIT\s+TO)\s+/i;
// A word that makes a street of the words before it; without one, the place is no street ("AIRPORT PARKING GARAGE").
const STREET_WORD = /\b(?:ST|STREET|AVE|AVENUE|RD|ROAD|DR|DRIVE|BLVD|BOULEVARD|PIKE|LN|LANE|PL|PLACE|PKWY|PARKWAY|WAY|HWY|HIGHWAY|CT|COURT|TER|TERRACE|CIR|CIRCLE|SQ|TOLL ROAD|US-\d+|MD-\d+|VA-\d+)\b/i;
// DC's own misspellings, where they would be said aloud.
const SPELLING: Record<string, string> = { ABLEMARLE: "ALBEMARLE" };
const KEPT_UPPER = new Set(["NW", "NE", "SW", "SE", "US", "MD", "VA", "DC", "I"]);

/** "WISCONSIN AVENUE NW" as "Wisconsin Avenue NW", "7TH" as "7th", "MD-355" as it is. */
function streetCase(words: string): string {
  return words
    .trim()
    .split(/\s+/)
    .map((word) => {
      const upper = SPELLING[word.toUpperCase()] ?? word.toUpperCase();
      if (KEPT_UPPER.has(upper) || /^[A-Z]+-\d/.test(upper)) return upper;
      if (/^\d+[A-Z]+$/.test(upper)) return upper.toLowerCase();
      return upper
        .split("-")
        .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
        .join("-");
    })
    .join(" ");
}

/** The compass side DC gives an entrance ("NE CORNER OF", "WEST SIDE OF"), as a word in the rider's language. */
function sideOf(text: string): string | null {
  const found = /^(N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST|NORTHEAST|NORTHWEST|SOUTHEAST|SOUTHWEST|NORTHEN|NORTHERN|SOUTHERN|EASTERN|WESTERN)\b/i.exec(text);
  if (!found) return null;
  const key = found[1].toUpperCase().replace(/ERN$|EN$/, "");
  const words: Record<string, () => string> = {
    N: () => t("north"),
    NORTH: () => t("north"),
    S: () => t("south"),
    SOUTH: () => t("south"),
    E: () => t("east"),
    EAST: () => t("east"),
    W: () => t("west"),
    WEST: () => t("west"),
    NE: () => t("northeast"),
    NORTHEAST: () => t("northeast"),
    NW: () => t("northwest"),
    NORTHWEST: () => t("northwest"),
    SE: () => t("southeast"),
    SOUTHEAST: () => t("southeast"),
    SW: () => t("southwest"),
    SOUTHWEST: () => t("southwest"),
  };
  return words[key]?.() ?? null;
}

/**
 * DC's words for where an entrance comes up, as a sentence: at a corner, "Take the exit at {street} and {cross}.";
 * along a street, "Take the exit on {street}."; null for a place that names no street. `withSide`: the side DC gives
 * too ("Take the east exit on Georgia Ave."), for a station whose exits would otherwise read alike.
 */
export function exitWords(to: string, withSide = false): string | null {
  const text = to
    .replace(/\s+/g, " ")
    .trim()
    // A building's name before the place ("RONALD REAGAN BUILDING - WEST SIDE OF 12TH STREET NW ..."); DC's typos.
    .replace(/^[^-]*\bBUILDING - /i, "")
    .replace(/\bANDG\b/i, "AND G")
    .replace(/\s*(?:\b(?:NORTH|SOUTH|EAST|WEST)\s+)?\b(?:INTERSECTION|ELEVATOR)$/i, "")
    .trim();
  const rest = text.replace(WHERE, "");
  if (!STREET_WORD.test(rest)) return null;
  const side = withSide && rest !== text ? sideOf(text) : null;
  const on = (street: string) =>
    side ? t("Take the {side} exit on {street}.", { side, street: streetCase(street) }) : t("Take the exit on {street}.", { street: streetCase(street) });
  const along = /^(.+?) BETWEEN .+$/i.exec(rest);
  if (along) return on(along[1]);
  const corner = /^(.+?) (?:AT (?:INTERSECTION WITH )?|AND )(.+)$/i.exec(rest);
  if (corner && STREET_WORD.test(corner[1]) && STREET_WORD.test(corner[2])) {
    const words = { street: streetCase(corner[1]), cross: streetCase(corner[2]) };
    return side ? t("Take the {side} exit at {street} and {cross}.", { side, ...words }) : t("Take the exit at {street} and {cross}.", words);
  }
  // One side of an "and" names no street ("BUS BAY AND BUNKER HILL RD NE"): the street alone.
  if (corner) return on(STREET_WORD.test(corner[1]) ? corner[1] : corner[2]);
  return on(rest);
}

/** Entrances this near one another are one station's (for telling its exits apart). */
const SAME_STATION_M = 400;

/**
 * The exit a walk starting at `point` leaves by, in words: the nearest entrance within EXIT_NEAR_M; else null. Where
 * another of the station's entrances reads the same, the side DC gives is said too.
 */
export function exitAt(exits: readonly StationExit[], point: LonLat | null | undefined): string | null {
  if (!point) return null;
  let best: { m: number; exit: StationExit } | null = null;
  for (const exit of exits) {
    const m = haversineM(point, exit.point);
    if (m <= EXIT_NEAR_M && (!best || m < best.m)) best = { m, exit };
  }
  if (!best) return null;
  const chosen = best.exit;
  const plain = exitWords(chosen.to);
  if (plain === null) return null;
  const alike = exits.some(
    (other) => other.to !== chosen.to && haversineM(other.point, chosen.point) <= SAME_STATION_M && haversineM(other.point, chosen.point) > 5 && exitWords(other.to) === plain,
  );
  return alike ? (exitWords(chosen.to, true) ?? plain) : plain;
}

/** DC's entrances file as exits: each point with its `EXIT_TO_ST`; none where it does not parse. */
export function parseExits(geojson: string): StationExit[] {
  try {
    const doc = JSON.parse(geojson) as { features?: { geometry?: { coordinates?: unknown }; properties?: { EXIT_TO_ST?: unknown } }[] };
    const out: StationExit[] = [];
    for (const feature of doc.features ?? []) {
      const at = feature.geometry?.coordinates;
      const to = feature.properties?.EXIT_TO_ST;
      if (Array.isArray(at) && typeof at[0] === "number" && typeof at[1] === "number" && typeof to === "string" && to.trim()) {
        out.push({ point: [at[0], at[1]], to });
      }
    }
    return out;
  } catch {
    return [];
  }
}
