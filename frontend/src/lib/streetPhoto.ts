/**
 * The road panel's street photo (v0.7.0; core/street_photo.py): the newest Mapillary photo of the road,
 * looked up by the server (GET /api/street-photo) so its token never reaches the browser.
 *
 * The owner, 2026-10-13: "Some of the photos are older, so make sure the date is listed too." The date
 * is under the photo ("Photo from June 2021") and in its alt text with the road's name; the photo is a
 * link to Mapillary's own viewer in a new tab (no embedded viewer), credited "Mapillary" (CC BY-SA).
 * No photo: one plain line, "No street photo here." A server with no token (204), or no answer, shows
 * nothing at all. No buttons, switches or map layer come with it.
 */
import type { LonLat } from "./geo.ts";

export const NO_PHOTO_TEXT = "No street photo here.";

export interface StreetPhoto {
  image_url: string;
  viewer_url: string;
  captured: string;
  /** "Photo from June 2021". */
  date_words: string;
  creator: string | null;
  credit: string;
  credit_url: string;
  licence: string;
  licence_url: string;
}

/** A photo, "none" (Mapillary has none of this road), or null (nothing to say: no token, no answer). */
export type PhotoAnswer = StreetPhoto | "none" | null;

type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

function https(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

/** The image is this server's own copy of Mapillary's file (the page's CSP names no other host). */
export function ownImage(value: unknown): value is string {
  return typeof value === "string" && /^\/api\/street-photo\/image\/\d{1,30}$/.test(value);
}

/** The answer read safely: the image this server's, every link https, every word a string. */
export function readPhoto(body: unknown): PhotoAnswer {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (b.found === false) return "none";
  if (b.found !== true) return null;
  if (!ownImage(b.image_url) || !https(b.viewer_url) || !https(b.credit_url) || !https(b.licence_url)) return null;
  if (typeof b.date_words !== "string" || typeof b.captured !== "string" || typeof b.credit !== "string" || typeof b.licence !== "string") {
    return null;
  }
  return {
    image_url: b.image_url,
    viewer_url: b.viewer_url,
    captured: b.captured,
    date_words: b.date_words,
    creator: typeof b.creator === "string" && b.creator.trim() ? b.creator : null,
    credit: b.credit,
    credit_url: b.credit_url,
    licence: b.licence,
    licence_url: b.licence_url,
  };
}

/** Where the photo is looked up: the road panel's own path, or Review's (the same lookup, counted in Review's reads,
 * since its lists show a photo a row; instance admins only). */
export type PhotoPath = "/api/street-photo" | "/api/review/street-photo";

export function streetPhotoUrl(origin: string, point: LonLat, wayId: number | null, path: PhotoPath = "/api/street-photo"): string {
  const [lon, lat] = point.map((v) => v.toFixed(6));
  const query = `lon=${lon}&lat=${lat}${wayId != null ? `&way=${wayId}` : ""}`;
  // Spelled out, so the beta's nginx test sees every path a place is sent to (tests/test_beta_overlay.py).
  return path === "/api/review/street-photo" ? `${origin}/api/review/street-photo?${query}` : `${origin}/api/street-photo?${query}`;
}

/** GET /api/street-photo (or Review's copy of it) for the point on the road. */
export async function fetchStreetPhoto(
  origin: string,
  point: LonLat,
  wayId: number | null,
  signal?: AbortSignal,
  fetchImpl: FetchLike = (url, init) => fetch(url, init),
  path: PhotoPath = "/api/street-photo",
): Promise<PhotoAnswer> {
  try {
    const response = await fetchImpl(streetPhotoUrl(origin, point, wayId, path), { headers: { Accept: "application/json" }, signal });
    if (response.status !== 200) return null;
    return readPhoto(await response.json());
  } catch {
    return null;
  }
}

/** The photo's alt text: the road's name and the date, "Street photo of Oak Street, from June 2021". */
export function photoAlt(title: string, photo: StreetPhoto): string {
  const when = photo.date_words.replace(/^Photo from /, "");
  return `Street photo of ${title}, from ${when}`;
}

/**
 * Each road's photo asked for once (Review's rows and card, and the road panel): the answer is kept by path and way
 * (by point where there is no way), so a re-render, a road opened again or its row scrolled back into view asks nothing. Where there was nothing
 * to say (null: no lookup possible, or the request failed) it is asked again after `retryMs`; at most `limit` are
 * kept, the oldest let go first.
 */
export function makePhotoMemo(limit = 500, retryMs = 60_000, now: () => number = () => Date.now()) {
  type Entry = { answer: Promise<PhotoAnswer>; known?: PhotoAnswer; at: number };
  const kept = new Map<string, Entry>();
  // A road by its way (its row and its card may name different points on it); a point with no way by the point.
  const keyOf = (path: PhotoPath, point: LonLat, wayId: number | null) => (wayId != null ? `${path}|way ${wayId}` : `${path}|${point[0].toFixed(6)},${point[1].toFixed(6)}`);
  const fresh = (key: string): Entry | undefined => {
    const entry = kept.get(key);
    if (entry && entry.known === null && now() - entry.at > retryMs) kept.delete(key);
    return kept.get(key);
  };
  return {
    /** The answer already in hand, or undefined while it is asked for (or never was). */
    known(path: PhotoPath, point: LonLat, wayId: number | null): PhotoAnswer | undefined {
      return fresh(keyOf(path, point, wayId))?.known;
    },
    get(path: PhotoPath, point: LonLat, wayId: number | null, load: () => Promise<PhotoAnswer>): Promise<PhotoAnswer> {
      const key = keyOf(path, point, wayId);
      const found = fresh(key);
      if (found) return found.answer;
      const entry: Entry = { answer: Promise.resolve(null), at: now() };
      entry.answer = load().then((answer) => {
        entry.known = answer;
        entry.at = now();
        return answer;
      });
      kept.set(key, entry);
      while (kept.size > limit) kept.delete(kept.keys().next().value as string);
      return entry.answer;
    },
  };
}
