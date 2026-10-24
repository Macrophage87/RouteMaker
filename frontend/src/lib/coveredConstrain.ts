// Keeping the map within its bounds when a panel covers its bottom (Stephen 2026-10-24: "When zooming out, you can't
// easily see the edges, specifically the bottom"). MapLibre's own bound check keeps the whole map box inside the
// bounds, so on a phone the area's south edge could go no higher than the screen's bottom, under Plan's sheet. This
// does the same check on the part of the map that shows: the box above the sheet. With nothing covered it is
// MapLibre's check (mercator_transform.ts defaultConstrain, without the world copies this area never needs).

export interface LngLatLike {
  lng: number;
  lat: number;
}

export interface ConstrainView {
  /** West, south, east, north in degrees. */
  bounds: readonly [number, number, number, number];
  minZoom: number;
  maxZoom: number;
  /** The map's size on screen in CSS pixels. */
  width: number;
  height: number;
  /** How many pixels at the map's bottom a panel hides (0 for none). */
  covered: number;
}

/** MapLibre's world size at zoom 0 (its tiles are 512 px). */
const TILE_SIZE = 512;
/** The map always keeps at least this much showing above a panel, whatever the panel's height. */
export const MIN_SHOWN_PX = 120;

const mercX = (lng: number) => (180 + lng) / 360;
const mercY = (lat: number) => (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) / 360;
const lngOf = (x: number) => x * 360 - 180;
const latOf = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(((180 - y * 360) * Math.PI) / 180)) - 90;

/** The pixels a panel hides, kept so some map always shows. */
export function shownCover(covered: number, height: number): number {
  if (!(covered > 0) || !(height > 0)) return 0;
  return Math.min(covered, Math.max(0, height - MIN_SHOWN_PX));
}

/** The centre and zoom to use for the asked ones, so the map above the panel stays within the bounds. */
export function constrainAbovePanel(center: LngLatLike, zoom: number, view: ConstrainView): { center: LngLatLike; zoom: number } {
  let z = Math.min(view.maxZoom, Math.max(view.minZoom, +zoom));
  const cover = shownCover(view.covered, view.height);
  const shownH = view.height - cover;
  const [west, south, east, north] = view.bounds;
  const world = TILE_SIZE * 2 ** z;
  const minX = mercX(west) * world;
  const maxX = mercX(east) * world;
  const minY = mercY(north) * world;
  const maxY = mercY(south) * world;
  const x = mercX(center.lng) * world;
  // The middle of the part that shows sits half the cover above the map's centre.
  const shownY = mercY(center.lat) * world - cover / 2;
  const scaleX = maxX - minX < view.width ? view.width / (maxX - minX) : 0;
  const scaleY = maxY - minY < shownH ? shownH / (maxY - minY) : 0;
  const scale = Math.max(scaleX, scaleY);
  if (scale) {
    // Zoomed out past the bounds: zoom in to them, centred on them along the side that was too small.
    z += Math.log2(scale);
    const lng = scaleX ? lngOf((minX + maxX) / 2 / world) : center.lng;
    // The cover is in screen pixels, which are `scale` times smaller in this zoom's world.
    const lat = scaleY ? latOf(((minY + maxY) / 2 + cover / 2 / scale) / world) : center.lat;
    return { center: { lng, lat }, zoom: z };
  }
  let nx = x;
  let ny = shownY;
  const h2 = shownH / 2;
  if (ny - h2 < minY) ny = minY + h2;
  if (ny + h2 > maxY) ny = maxY - h2;
  const w2 = view.width / 2;
  if (nx - w2 < minX) nx = minX + w2;
  if (nx + w2 > maxX) nx = maxX - w2;
  if (nx === x && ny === shownY) return { center: { lng: center.lng, lat: center.lat }, zoom: z };
  return { center: { lng: nx === x ? center.lng : lngOf(nx / world), lat: ny === shownY ? center.lat : latOf((ny + cover / 2) / world) }, zoom: z };
}
