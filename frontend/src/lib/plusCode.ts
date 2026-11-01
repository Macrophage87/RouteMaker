/**
 * Plus codes (Open Location Code), read in the search box (Stephen, 2026-10-31: "We should be able to add locations
 * by latitude and longitude in the search. If possible plus codes ... too").
 *
 * The code is an open specification (github.com/google/open-location-code, docs/specification.md, Apache 2.0) and
 * is decoded here, on the phone, from the code alone: nothing is sent anywhere.
 *
 * - A full code, "87C4VXQ7+GV", is a point anywhere on Earth.
 * - A short code, "VXQ7+GV" (Google Maps shows it with a town, "VXQ7+GV Washington, District of Columbia"), leaves
 *   out its first digits, which are recovered from a point near it: the route's start or the map's view, else the
 *   middle of this map. The town after it is not read; within this map's area the nearest recovery is the place.
 */
import { COVERAGE_BBOX, type LonLat } from "./geo.ts";

const ALPHABET = "23456789CFGHJMPQRVWX";
const SEPARATOR = "+";
const SEPARATOR_POSITION = 8;
const PADDING = "0";
const PAIR_CODE_LENGTH = 10;
/** The degrees each pair of digits stands for: 20, 1, 1/20, 1/400, 1/8000. */
const PAIR_RESOLUTIONS = [20, 1, 0.05, 0.0025, 0.000125];
const GRID_ROWS = 5;
const GRID_COLUMNS = 4;
/** Digits past this many add nothing a bike route needs (and the spec stops at 15). */
const MAX_DIGITS = 15;

/** The middle of this map's area: the reference for a short code when no nearer point is known. */
export const COVERAGE_CENTRE: LonLat = [(COVERAGE_BBOX[0] + COVERAGE_BBOX[2]) / 2, (COVERAGE_BBOX[1] + COVERAGE_BBOX[3]) / 2];

const CODE = new RegExp(String.raw`^[${ALPHABET}${PADDING}]{2,8}\+[${ALPHABET}]{0,15}$`, "i");

/** Whether `code` is a well-formed plus code, full or short (the spec's isValid). */
export function isValidPlusCode(code: string): boolean {
  if (!CODE.test(code)) return false;
  const c = code.toUpperCase();
  const sep = c.indexOf(SEPARATOR);
  if (sep % 2 === 1) return false;
  const after = c.length - sep - 1;
  if (after === 1) return false;
  const pad = c.indexOf(PADDING);
  if (pad !== -1) {
    // Padding: only in a full code, in whole pairs, up to the separator, with nothing after the separator.
    if (pad === 0 || pad % 2 === 1 || sep !== SEPARATOR_POSITION || after > 0) return false;
    if (!/^0+$/.test(c.slice(pad, sep))) return false;
  }
  return true;
}

/** A full code: eight digits (or padding) before the separator, inside the world's latitude and longitude. */
export function isFullPlusCode(code: string): boolean {
  if (!isValidPlusCode(code)) return false;
  const c = code.toUpperCase();
  if (c.indexOf(SEPARATOR) !== SEPARATOR_POSITION) return false;
  return ALPHABET.indexOf(c[0]) * 20 < 180 && ALPHABET.indexOf(c[1]) * 20 < 360;
}

/** A short code: a valid code with fewer than eight digits before the separator (no padding). */
export function isShortPlusCode(code: string): boolean {
  return isValidPlusCode(code) && code.indexOf(SEPARATOR) < SEPARATOR_POSITION && code.indexOf(PADDING) === -1;
}

/** A full code's area: its south-west corner and its size, in degrees. */
function decodeArea(code: string): { south: number; west: number; height: number; width: number } {
  const digits = code.toUpperCase().replace(SEPARATOR, "").replace(/0+$/, "").slice(0, MAX_DIGITS);
  let south = -90;
  let west = -180;
  let height = 0;
  let width = 0;
  const pairs = Math.min(digits.length, PAIR_CODE_LENGTH);
  for (let i = 0; i < pairs; i += 2) {
    const r = PAIR_RESOLUTIONS[i / 2];
    south += ALPHABET.indexOf(digits[i]) * r;
    height = width = r;
    if (i + 1 < pairs) west += ALPHABET.indexOf(digits[i + 1]) * r;
  }
  for (let i = PAIR_CODE_LENGTH; i < digits.length; i += 1) {
    height /= GRID_ROWS;
    width /= GRID_COLUMNS;
    const v = ALPHABET.indexOf(digits[i]);
    south += Math.floor(v / GRID_COLUMNS) * height;
    west += (v % GRID_COLUMNS) * width;
  }
  return { south, west, height, width };
}

/** A full code's centre as [lon, lat]; null if it is not a full code. */
export function decodePlusCode(code: string): LonLat | null {
  if (!isFullPlusCode(code)) return null;
  const a = decodeArea(code);
  const lat = Math.min(90, a.south + a.height / 2);
  const lon = Math.min(180, a.west + a.width / 2);
  return [lon, lat];
}

/** The first `length` digits of the full code of a point (as many as a short code needs from its reference). */
function pairDigits(point: LonLat, length: number): string {
  let lat = Math.min(Math.max(point[1], -90), 90 - 1e-9) + 90;
  let lon = ((((point[0] + 180) % 360) + 360) % 360);
  let out = "";
  for (let i = 0; i < length / 2; i += 1) {
    const r = PAIR_RESOLUTIONS[i];
    const la = Math.min(19, Math.floor(lat / r));
    const lo = Math.min(19, Math.floor(lon / r));
    out += ALPHABET[la] + ALPHABET[lo];
    lat -= la * r;
    lon -= lo * r;
  }
  return out;
}

/**
 * A short code's place, the one nearest `reference` (the spec's recoverNearest), as [lon, lat]; a full code is
 * decoded as it is. Null if it is neither.
 */
export function recoverPlusCode(code: string, reference: LonLat): LonLat | null {
  if (isFullPlusCode(code)) return decodePlusCode(code);
  if (!isShortPlusCode(code)) return null;
  const c = code.toUpperCase();
  const missing = SEPARATOR_POSITION - c.indexOf(SEPARATOR);
  const resolution = 20 ** (2 - missing / 2);
  const half = resolution / 2;
  const centre = decodePlusCode(pairDigits(reference, missing) + c);
  if (!centre) return null;
  let [lon, lat] = centre;
  const [refLon, refLat] = reference;
  if (refLat + half < lat && lat - resolution >= -90) lat -= resolution;
  else if (refLat - half > lat && lat + resolution <= 90) lat += resolution;
  if (refLon + half < lon) lon -= resolution;
  else if (refLon - half > lon) lon += resolution;
  return [lon, lat];
}

// A code, then (Google's short codes) words for the town: "VXQ7+GV Washington, District of Columbia".
const IN_TEXT = new RegExp(String.raw`^\s*([${ALPHABET}${PADDING}]{2,8}\+[${ALPHABET}]{0,15})(?=$|[\s,])[\s,]*(.*)$`, "i");

/**
 * A plus code typed or pasted in the box: its place (a short one recovered near `reference`) and the code, upper
 * case, as the place's name. Null when the text is not a plus code, or (a short code) has no digits after the
 * separator to place it.
 */
export function parsePlusCode(text: string, reference: LonLat = COVERAGE_CENTRE): { point: LonLat; code: string } | null {
  const m = IN_TEXT.exec(text);
  if (!m) return null;
  const code = m[1].toUpperCase();
  if (!isValidPlusCode(code)) return null;
  // Digits only ("22+22", "2345+67") are more likely numbers than a code: a real one nearly always has a letter.
  if (!/[A-Z]/.test(code)) return null;
  // A short code needs its last digits, or it is a whole region; a full code with padding is a region too.
  if (!isFullPlusCode(code) && code.endsWith(SEPARATOR)) return null;
  if (code.includes(PADDING)) return null;
  const point = recoverPlusCode(code, reference);
  return point ? { point, code } : null;
}
