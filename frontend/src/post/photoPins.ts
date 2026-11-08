/**
 * A Featured routes post's photos on its maps (the owner, 2026-11-08: "put the photos as popouts on the map" and, on
 * the section maps, "a thumbnail pointing to where it was taken"). Only photos that know where they were taken
 * (core/route_posts.py page_data `photos`); kept apart from the map code so it can be tested without a browser.
 */

/** One photo as the page data gives it. */
export interface PostPhoto {
  url: string;
  lon: number;
  lat: number;
  alt: string;
  caption?: string;
}

export const PHOTO_PIN_LABEL = "Photo";
/** How far past a section map's stretch (as a share of its size) a photo still shows on it. */
export const STRETCH_MARGIN = 0.15;

/** The photos the page data gives, those with a real spot and an address on this site. */
export function photoPins(raw: unknown): PostPhoto[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (p): p is PostPhoto =>
      !!p &&
      typeof p === "object" &&
      typeof p.url === "string" &&
      p.url.startsWith("/routes/") &&
      typeof p.alt === "string" &&
      Number.isFinite(p.lon) &&
      Number.isFinite(p.lat) &&
      Math.abs(p.lon) <= 180 &&
      Math.abs(p.lat) <= 90,
  );
}

/** The photos taken on or near a stretch: inside its extent, widened by STRETCH_MARGIN on each side. */
export function photosNear(stretch: readonly number[][], photos: readonly PostPhoto[]): PostPhoto[] {
  if (stretch.length < 2) return [];
  let [west, south, east, north] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const p of stretch) {
    west = Math.min(west, p[0]);
    east = Math.max(east, p[0]);
    south = Math.min(south, p[1]);
    north = Math.max(north, p[1]);
  }
  const dx = Math.max(east - west, 0.002) * STRETCH_MARGIN;
  const dy = Math.max(north - south, 0.002) * STRETCH_MARGIN;
  return photos.filter((p) => p.lon >= west - dx && p.lon <= east + dx && p.lat >= south - dy && p.lat <= north + dy);
}

/** The words a photo's pin is read out as. */
export function pinLabel(photo: PostPhoto): string {
  return `${PHOTO_PIN_LABEL}: ${photo.alt}`;
}

/** A screen point, in pixels. */
export type Px = readonly [number, number];

/**
 * Where a photo's thumbnail sits beside the route rather than on it (the owner, 2026-11-08: "pop out beside the trail
 * at a point, not on it"): `distance` pixels from the photo's spot, square to the route's nearest stretch, on the side
 * nearer the map's middle so it stays in the frame. `line` is the route in screen pixels; with no stretch to go by the
 * thumbnail goes straight up.
 */
export function besideOffset(spot: Px, line: readonly Px[], middle: Px, distance: number): { dx: number; dy: number } {
  let best = Infinity;
  let along: [number, number] | null = null;
  for (let i = 1; i < line.length; i++) {
    const [ax, ay] = line[i - 1];
    const [bx, by] = line[i];
    const vx = bx - ax;
    const vy = by - ay;
    const length2 = vx * vx + vy * vy;
    if (length2 === 0) continue;
    const t = Math.max(0, Math.min(1, ((spot[0] - ax) * vx + (spot[1] - ay) * vy) / length2));
    const gap = Math.hypot(ax + t * vx - spot[0], ay + t * vy - spot[1]);
    if (gap < best) {
      best = gap;
      along = [vx, vy];
    }
  }
  if (!along) return { dx: 0, dy: -distance };
  const length = Math.hypot(along[0], along[1]);
  const nx = -along[1] / length;
  const ny = along[0] / length;
  const toMiddle = (middle[0] - spot[0]) * nx + (middle[1] - spot[1]) * ny;
  const side = toMiddle >= 0 ? 1 : -1;
  return { dx: side * nx * distance, dy: side * ny * distance };
}
