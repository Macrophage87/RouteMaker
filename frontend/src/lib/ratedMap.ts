/**
 * The rated junctions on the plain map (the owner, 2026-11-20: "They should only show at intersections at the closest
 * zoom or on a planned route"; "Anything less than 3 only show at the very closest zoom level"): those rated 3 or more
 * asked for the map's view from zoom 17, every one at its closest (GET /api/junctions/rated), each a small dot in
 * its hardest movement's stress colour that opens a card of its movements. A planned route's own junctions keep their
 * own dots (lib/intersectionMarkers.ts), in the colour of the movement the route makes.
 */
import type { RatedMove } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { ratedDotSvg, ratedLines } from "./intersectionMarkers.ts";
import { ratedLevelText } from "./ratedDot.ts";

/** The map's two closest zooms (its most is 18): the junctions rated 3 or more from the first, every one at the last. */
export const RATED_MIN_ZOOM = 17;
export const RATED_EVERY_ZOOM = 17.75;
/** The server's largest view (core.junction_raters BOX_MAX_LON, BOX_MAX_LAT). */
const MAX_LON = 0.04;
const MAX_LAT = 0.03;
/** A route's own dot within this of a map dot stands for it. */
const SAME_SPOT_M = 20;

export interface RatedMapJunction {
  lon: number;
  lat: number;
  level: number;
  moves: RatedMove[];
}

interface View {
  west: number;
  south: number;
  east: number;
  north: number;
}

/**
 * What to ask for the view: the view padded to twice its size, cut to the server's largest, so small moves ask nothing
 * more (lib/closureMap.ts viewInside). Null when zoomed out, or where the view is larger than the server answers.
 */
export function ratedMapAsk(view: View, zoom: number): { path: string; box: View; every: boolean } | null {
  if (zoom < RATED_MIN_ZOOM) return null;
  if (view.east - view.west > MAX_LON || view.north - view.south > MAX_LAT) return null;
  const cx = (view.west + view.east) / 2;
  const cy = (view.south + view.north) / 2;
  // A hair under the server's largest, so rounding never takes the box over it (a 400 draws nothing).
  const halfLon = Math.min((view.east - view.west) * 2, MAX_LON - 2e-4) / 2;
  const halfLat = Math.min((view.north - view.south) * 2, MAX_LAT - 2e-4) / 2;
  const r = (v: number) => Math.round(v * 1e4) / 1e4;
  const box = { west: r(cx - halfLon), south: r(cy - halfLat), east: r(cx + halfLon), north: r(cy + halfLat) };
  const every = zoom >= RATED_EVERY_ZOOM;
  const bbox = encodeURIComponent([box.west, box.south, box.east, box.north].join(","));
  return { path: `/api/junctions/rated?bbox=${bbox}${every ? "&every=true" : ""}`, box, every };
}

function parse(value: unknown): RatedMapJunction[] {
  const list = (value as { junctions?: unknown } | null)?.junctions;
  if (!Array.isArray(list)) return [];
  return list.filter(
    (j): j is RatedMapJunction => !!j && typeof j.lon === "number" && typeof j.lat === "number" && typeof j.level === "number" && Array.isArray(j.moves),
  );
}

/** GET the view's rated junctions; null when it could not be asked (offline, refused, aborted): the last stay drawn. */
export async function loadRatedMap(
  path: string,
  signal?: AbortSignal,
  fetcher: (url: string, init?: RequestInit) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u, init) => fetch(u, init),
): Promise<RatedMapJunction[] | null> {
  try {
    const response = await fetcher(path, { signal });
    if (signal?.aborted || !response.ok) return null;
    return parse(await response.json());
  } catch {
    return null;
  }
}

/** The map's dots with a planned route drawn: none on the route itself, whose own markers show its junctions in the
 * colour of the movement it makes there (a dot in its hardest movement's colour would contradict them), and none
 * where those markers stand. `line` is the route's line. */
export function ratedMapShown(
  junctions: readonly RatedMapJunction[],
  onRoute: readonly LonLat[],
  line: readonly LonLat[] = [],
): RatedMapJunction[] {
  if (!onRoute.length && line.length < 2) return [...junctions];
  return junctions.filter((j) => {
    const at: LonLat = [j.lon, j.lat];
    return !onRoute.some((spot) => haversineM(spot, at) <= SAME_SPOT_M) && !nearLine(at, line, SAME_SPOT_M);
  });
}

/** Whether `at` is within `m` metres of the line (a flat projection, fine at these distances). */
function nearLine(at: LonLat, line: readonly LonLat[], m: number): boolean {
  const kx = 111_320 * Math.cos((at[1] * Math.PI) / 180);
  const ky = 110_540;
  for (let i = 1; i < line.length; i += 1) {
    const ax = (line[i - 1][0] - at[0]) * kx;
    const ay = (line[i - 1][1] - at[1]) * ky;
    const bx = (line[i][0] - at[0]) * kx;
    const by = (line[i][1] - at[1]) * ky;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
    if (Math.hypot(ax + t * dx, ay + t * dy) <= m) return true;
  }
  return false;
}

/** "Junction rated LTS 4": the dot's name, and its card's title. */
export function ratedMapName(junction: Pick<RatedMapJunction, "level">): string {
  return `Junction rated ${ratedLevelText(junction.level)}`;
}

/** The dot: a button named by its level, drawn small and in colour only. */
export function ratedMapDot(junction: RatedMapJunction): HTMLButtonElement {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "rated-map-dot";
  element.setAttribute("aria-label", ratedMapName(junction));
  element.setAttribute("aria-haspopup", "dialog");
  element.innerHTML = ratedDotSvg(junction.level, 24);
  element.addEventListener("dblclick", (event) => event.stopPropagation());
  return element;
}

/** The card a dot opens: the junction's level, then each movement that can be made there with its level and wait. */
export function ratedMapCardBody(junction: RatedMapJunction): HTMLDivElement {
  const body = document.createElement("div");
  body.className = "junction-card";
  const title = document.createElement("strong");
  title.textContent = ratedMapName(junction);
  const moves = document.createElement("ul");
  moves.className = "junction-card-moves";
  for (const line of ratedLines({ moves: junction.moves })) {
    const row = document.createElement("li");
    row.textContent = line.text;
    moves.append(row);
  }
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "The dot is the colour of its hardest movement.";
  body.append(title, moves, hint);
  return body;
}
