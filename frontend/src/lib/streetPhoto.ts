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

export function streetPhotoUrl(origin: string, point: LonLat, wayId: number | null): string {
  const [lon, lat] = point.map((v) => v.toFixed(6));
  return `${origin}/api/street-photo?lon=${lon}&lat=${lat}${wayId != null ? `&way=${wayId}` : ""}`;
}

/** GET /api/street-photo for the point on the road. */
export async function fetchStreetPhoto(
  origin: string,
  point: LonLat,
  wayId: number | null,
  signal?: AbortSignal,
  fetchImpl: FetchLike = (url, init) => fetch(url, init),
): Promise<PhotoAnswer> {
  try {
    const response = await fetchImpl(streetPhotoUrl(origin, point, wayId), { headers: { Accept: "application/json" }, signal });
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
