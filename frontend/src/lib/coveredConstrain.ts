// Keeping the map within its bounds when a panel covers its bottom (Stephen 2026-10-24: "When zooming out, you can't
// easily see the edges, specifically the bottom"). MapLibre's own bound check keeps the whole map box inside the
// bounds, so on a phone the area's south edge could go no higher than the screen's bottom, under Plan's sheet. This
// does the same check on the part of the map that shows: the box above the sheet, measured from the map's centre
// point (which padding moves). With nothing covered and no padding it is MapLibre's check (mercator_transform.ts
// defaultConstrain, without the world copies this area never needs). A turned map gets MapLibre's check, as the
// sheet then covers no one side of the area.

export interface LngLatLike {
  lng: number;
  lat: number;
}

/** As MapLibre's getPadding gives it: a side missing is 0. */
export interface Padding {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
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
  /** The map's padding, which puts its centre point off the middle (an easeTo with a frame leaves it set). */
  padding?: Padding;
  /** The map's bearing in degrees. */
  bearing?: number;
}

/** MapLibre's world size at zoom 0 (its tiles are 512 px). */
const TILE_SIZE = 512;
/** The map always keeps at least this much showing above a panel, whatever the panel's height. */
export const MIN_SHOWN_PX = 120;
const NO_PADDING: Padding = { top: 0, bottom: 0, left: 0, right: 0 };

const mercX = (lng: number) => (180 + lng) / 360;
const mercY = (lat: number) => (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) / 360;
const lngOf = (x: number) => x * 360 - 180;
const latOf = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(((180 - y * 360) * Math.PI) / 180)) - 90;

/** The pixels a panel hides, kept so some map always shows. */
export function shownCover(covered: number, height: number): number {
  if (!(covered > 0) || !(height > 0)) return 0;
  return Math.min(covered, Math.max(0, height - MIN_SHOWN_PX));
}

/** True when the map is turned off north-up. */
export function turned(bearing: number | undefined): boolean {
  const off = Math.abs((((bearing ?? 0) % 360) + 360) % 360);
  return Math.min(off, 360 - off) > 0.01;
}

/** One axis: where the centre goes so the span shown (`before` px ahead of it, `after` px past it) stays in [min, max]. */
function clampAxis(at: number, before: number, after: number, min: number, max: number): number {
  if (at - before < min) return min + before;
  if (at + after > max) return max - after;
  return at;
}

/** The centre and zoom to use for the asked ones, so the map above the panel stays within the bounds. */
export function constrainAbovePanel(center: LngLatLike, zoom: number, view: ConstrainView): { center: LngLatLike; zoom: number } {
  let z = Math.min(view.maxZoom, Math.max(view.minZoom, +zoom));
  const northUp = !turned(view.bearing);
  const given = northUp ? (view.padding ?? NO_PADDING) : NO_PADDING;
  const pad = { top: given.top ?? 0, bottom: given.bottom ?? 0, left: given.left ?? 0, right: given.right ?? 0 };
  const cover = northUp ? shownCover(view.covered, view.height) : 0;
  const { width: w, height: h } = view;
  // The centre point on screen, and the part shown from it: up to the top, down to the panel's top, to each side.
  const cx = pad.left + (w - pad.left - pad.right) / 2;
  const cy = pad.top + (h - pad.top - pad.bottom) / 2;
  const up = cy;
  const down = h - cover - cy;
  const left = cx;
  const right = w - cx;
  const [west, south, east, north] = view.bounds;
  let world = TILE_SIZE * 2 ** z;
  const spanX = (mercX(east) - mercX(west)) * world;
  const spanY = (mercY(south) - mercY(north)) * world;
  const scaleX = spanX < left + right ? (left + right) / spanX : 0;
  const scaleY = spanY < up + down ? (up + down) / spanY : 0;
  const scale = Math.max(scaleX, scaleY);
  if (scale) {
    // Zoomed out past the bounds: zoom in to them, the part shown centred on them along the side that was too small.
    z += Math.log2(scale);
    world = TILE_SIZE * 2 ** z;
    const lng = scaleX ? lngOf((mercX(west) + mercX(east)) / 2 + (left - right) / 2 / world) : center.lng;
    const lat = scaleY ? latOf((mercY(north) + mercY(south)) / 2 + (up - down) / 2 / world) : center.lat;
    return { center: { lng, lat }, zoom: z };
  }
  const x = mercX(center.lng) * world;
  const y = mercY(center.lat) * world;
  const nx = clampAxis(x, left, right, mercX(west) * world, mercX(east) * world);
  const ny = clampAxis(y, up, down, mercY(north) * world, mercY(south) * world);
  return {
    center: { lng: nx === x ? center.lng : lngOf(nx / world), lat: ny === y ? center.lat : latOf(ny / world) },
    zoom: z,
  };
}
