/**
 * The rated junctions on the plain map (the owner, 2026-11-20: "They should only show at intersections at the closest
 * zoom or on a planned route"; "Anything less than 3 only show at the very closest zoom level"): those rated 3 or more
 * asked for the map's view from zoom 17, every one at its closest (GET /api/junctions/rated), each a small dot in
 * its hardest movement's stress colour that opens a card of its movements. A planned route's own junctions keep their
 * own dots (lib/intersectionMarkers.ts), in the colour of the movement the route makes.
 */
import type { RatedMove } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { movementIconSvg, ratedDotSvg, ratedLines, type Movement } from "./intersectionMarkers.ts";
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
  /** Set where the planned route rides through it without a marker of its own: the movement the route makes there. */
  routeMove?: Movement;
}

/** A dot this near the route's line is one the route rides through (our default, unmeasured). */
const ON_LINE_M = 8;
/** The route's heading in and out of a junction is read this far before and after it (our default, unmeasured). */
const HEADING_M = 25;
/** A change of heading of more than this is a turn, a bend in the road less (our default, unmeasured). */
const TURN_DEG = 35;

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

/** Metres east and north of `origin`, near enough for a junction's few tens of metres. */
function local(origin: LonLat, p: LonLat): [number, number] {
  const k = 111_320;
  return [(p[0] - origin[0]) * k * Math.cos((origin[1] * Math.PI) / 180), (p[1] - origin[1]) * k];
}

/** The point `metres` along the line from the spot `at` on segment `i` (negative: back along it). */
function along(line: readonly LonLat[], i: number, at: LonLat, metres: number): LonLat {
  let left = Math.abs(metres);
  let from = at;
  if (metres >= 0) {
    for (let j = i + 1; j < line.length; j += 1) {
      const step = haversineM(from, line[j]);
      if (step >= left) return lerp(from, line[j], left / step);
      left -= step;
      from = line[j];
    }
  } else {
    for (let j = i; j >= 0; j -= 1) {
      const step = haversineM(from, line[j]);
      if (step >= left) return lerp(from, line[j], left / step);
      left -= step;
      from = line[j];
    }
  }
  return from;
}

function lerp(a: LonLat, b: LonLat, f: number): LonLat {
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
}

/**
 * The movement the route's line makes at a spot: "left", "right" or "straight" by its heading HEADING_M before and
 * after, or null where the line does not pass within ON_LINE_M of it. A route through the same spot twice is read at
 * its nearest pass.
 */
export function routeMoveAt(line: readonly LonLat[], spot: LonLat): Movement | null {
  let best: { i: number; at: LonLat; m: number } | null = null;
  for (let i = 0; i + 1 < line.length; i += 1) {
    const [ax, ay] = local(spot, line[i]);
    const [bx, by] = local(spot, line[i + 1]);
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const f = len2 > 0 ? Math.min(1, Math.max(0, -(ax * dx + ay * dy) / len2)) : 0;
    const m = Math.hypot(ax + dx * f, ay + dy * f);
    if (m <= ON_LINE_M && (!best || m < best.m)) best = { i, at: lerp(line[i], line[i + 1], f), m };
  }
  if (!best) return null;
  const [inX, inY] = local(along(line, best.i, best.at, -HEADING_M), best.at);
  const [outX, outY] = local(best.at, along(line, best.i, best.at, HEADING_M));
  if (Math.hypot(inX, inY) < 1 || Math.hypot(outX, outY) < 1) return "straight";
  const turn = (Math.atan2(inX * outY - inY * outX, inX * outX + inY * outY) * 180) / Math.PI;
  if (turn > TURN_DEG) return "left";
  if (turn < -TURN_DEG) return "right";
  return "straight";
}

/** The map's dots with a planned route drawn: every one, the route's own junctions included (the owner, 2026-11-22:
 * "Intersections along the route aren't shown"), except where the route's own marker stands for it. A dot the route
 * rides through without a marker carries the movement the route makes there (`routeMove`), drawn without a stress
 * colour: the route marks every movement it makes rated 3 or more (the owner, 2026-11-22: "show the movement done at
 * each intersection colored by the movement when LtS >=3"), so never the junction's hardest movement. */
export function ratedMapShown(
  junctions: readonly RatedMapJunction[],
  onRoute: readonly LonLat[],
  line: readonly LonLat[] = [],
  marked: readonly LonLat[] = onRoute,
): RatedMapJunction[] {
  const near = (spots: readonly LonLat[], j: RatedMapJunction) => spots.some((spot) => haversineM(spot, [j.lon, j.lat]) <= SAME_SPOT_M);
  return junctions
    .filter((j) => !near(onRoute, j))
    .map((j) => {
      // A marked junction past the map's most drawn (`marked` less `onRoute`) keeps its plain dot.
      const move = line.length > 1 && !near(marked, j) ? routeMoveAt(line, [j.lon, j.lat]) : null;
      return move ? { ...j, routeMove: move } : j;
    });
}

/** Whether the dot's own ratings agree that the route's movement there is below 3: a left's own level, or straight
 * through both crossing and riding along (the line cannot tell which). A right has no rating. */
function belowThree(moves: readonly RatedMove[], move: Movement): boolean {
  if (move === "right") return false;
  const names: RatedMove["move"][] = move === "left" ? ["left"] : ["cross", "along"];
  return moves.length > 0 && moves.filter((m) => names.includes(m.move)).every((m) => m.level < 3);
}

const ROUTE_MOVE_WORDS: Record<Movement, string> = {
  left: "This route turns left here",
  right: "This route turns right here",
  straight: "This route rides straight through here",
};

/** "Junction rated LTS 4": the dot's name, and its card's title. */
export function ratedMapName(junction: Pick<RatedMapJunction, "level" | "routeMove"> & Partial<Pick<RatedMapJunction, "moves">>): string {
  // Said to be below 3 only where the dot's own ratings agree (a right has none: the model prices it).
  if (junction.routeMove) return belowThree(junction.moves ?? [], junction.routeMove) ? `${ROUTE_MOVE_WORDS[junction.routeMove]}, below LTS 3` : ROUTE_MOVE_WORDS[junction.routeMove];
  return `Junction rated ${ratedLevelText(junction.level)}`;
}

/** The dot: a button named by its level, drawn small and in colour only. */
export function ratedMapDot(junction: RatedMapJunction): HTMLButtonElement {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "rated-map-dot";
  element.setAttribute("aria-label", ratedMapName(junction));
  element.setAttribute("aria-haspopup", "dialog");
  element.innerHTML = junction.routeMove ? movementIconSvg(junction.routeMove, null, 24) : ratedDotSvg(junction.level, 24);
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
  body.append(title, moves);
  if (!junction.routeMove) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "The dot is the colour of its hardest movement.";
    body.append(hint);
  }
  return body;
}
