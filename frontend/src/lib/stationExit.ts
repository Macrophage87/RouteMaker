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

/**
 * DC's words for where an entrance comes up, as a sentence: at a corner, "Take the exit at {street} and {cross}.";
 * along a street, "Take the exit on {street}."; null for a place that names no street.
 */
export function exitWords(to: string): string | null {
  const text = to.replace(/\s+/g, " ").trim().replace(/\s*(?:\b(?:NORTH|SOUTH|EAST|WEST)\s+)?\b(?:INTERSECTION|ELEVATOR)$/i, "").trim();
  const rest = text.replace(WHERE, "");
  if (!STREET_WORD.test(rest)) return null;
  const along = /^(.+?) BETWEEN .+$/i.exec(rest);
  if (along) return t("Take the exit on {street}.", { street: streetCase(along[1]) });
  const corner = /^(.+?) (?:AT (?:INTERSECTION WITH )?|AND )(.+)$/i.exec(rest);
  if (corner && STREET_WORD.test(corner[1]) && STREET_WORD.test(corner[2])) {
    return t("Take the exit at {street} and {cross}.", { street: streetCase(corner[1]), cross: streetCase(corner[2]) });
  }
  return t("Take the exit on {street}.", { street: streetCase(corner && STREET_WORD.test(corner[1]) ? corner[1] : rest) });
}

/** The exit a walk starting at `point` leaves by, in words: the nearest entrance within EXIT_NEAR_M; else null. */
export function exitAt(exits: readonly StationExit[], point: LonLat | null | undefined): string | null {
  if (!point) return null;
  let best: { m: number; exit: StationExit } | null = null;
  for (const exit of exits) {
    const m = haversineM(point, exit.point);
    if (m <= EXIT_NEAR_M && (!best || m < best.m)) best = { m, exit };
  }
  return best ? exitWords(best.exit.to) : null;
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
