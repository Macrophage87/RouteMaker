/**
 * EVERY STREET NAMED IN A RIDE. The owner, 2026-10-24: "try to make it so that all streets are labeled in ride mode
 * on the default look". MapLibre places labels from the top layer down, and a label that would overlap one already
 * placed is left out. The base map's street names (stressStyle.js ROAD_LABEL_LAYER_IDS) sit low in the stack: the
 * base map's shops and cafes (`pois`), its neighbourhood and town names (whose 18-20 px padding clears a wide box
 * round each), our water, restroom and repair icons and the route's hazard repeats are all above them, so each one
 * took its spot first and a street name near it went missing, most of all at the ride's 20 px.
 *
 * In a ride the street names, and the major trails' names under them (TRAIL_LABEL), go up to just under the station
 * names (railLayer.ts stationNamesTarget): placed before everything but the station names, the hazard marks, the ride
 * dots and Review's layers, they win their spot and the shops' names and icons give way. Drawn there, a name is also
 * over the route line on its white halo, so the street the rider is on can be read. After the ride they go back where
 * the base map put them, and Plan and the overview keep their own order.
 */
import { OVER_STATION_NAMES, RAIL_LAYERS } from "./railLayer.ts";
import { ROAD_LABEL_LAYER_IDS, TRAIL_LABEL_LAYER_ID } from "../stressStyle.js";

/** The ride's lifted labels, bottom first: the trails' names under the minor streets', under the major roads'. */
export const RIDE_LABEL_LAYERS: readonly string[] = [TRAIL_LABEL_LAYER_ID, ...ROAD_LABEL_LAYER_IDS.slice().reverse()];

/**
 * Where the ride's labels go in `order` (the map's layers, bottom first): together, in RIDE_LABEL_LAYERS' order,
 * directly under the station names (or, without them, under the first layer that stays over them). `null` when they
 * are there already; otherwise the moveLayer target each goes under, bottom first (`undefined` = the very top).
 */
export function rideLabelsTarget(order: readonly string[]): { before: string | undefined } | null {
  const lifted = RIDE_LABEL_LAYERS.filter((id) => order.includes(id));
  if (lifted.length === 0) return null;
  const rest = order.filter((id) => !lifted.includes(id));
  const over = (id: string) => id === RAIL_LAYERS.names || OVER_STATION_NAMES.some((prefix) => id.startsWith(prefix));
  const first = rest.findIndex(over);
  const at = first === -1 ? rest.length : first;
  const want = [...rest.slice(0, at), ...lifted, ...rest.slice(at)];
  if (want.every((id, i) => order[i] === id)) return null;
  return { before: rest[at] };
}

/** Each lifted label's home: the layer it was under before the ride lifted it (`undefined` = the very top). */
export type LabelHomes = Map<string, string | undefined>;

/** The labels' homes in `order`: the next layer up from each (put back top first, a lifted one is home by then). */
export function labelHomes(order: readonly string[]): LabelHomes {
  const homes: LabelHomes = new Map();
  for (const id of RIDE_LABEL_LAYERS) {
    const at = order.indexOf(id);
    if (at === -1) continue;
    homes.set(id, order[at + 1]);
  }
  return homes;
}

/** The parts of a MapLibre map the lift uses. */
export interface LabelOrderMap {
  getLayersOrder(): string[];
  getLayer(id: string): unknown;
  moveLayer(id: string, beforeId?: string): void;
}

/**
 * Lift the labels for a ride, or put them home after one. `homes` is filled on the first lift (from the order the
 * map had then) and emptied when they are home; a home that is gone (a style reload) leaves the label where it is.
 */
export function setRideLabelOrder(map: LabelOrderMap, riding: boolean, homes: LabelHomes): void {
  if (riding) {
    const move = rideLabelsTarget(map.getLayersOrder());
    if (!move) return;
    if (homes.size === 0) for (const [id, home] of labelHomes(map.getLayersOrder())) homes.set(id, home);
    for (const id of RIDE_LABEL_LAYERS) if (map.getLayer(id)) map.moveLayer(id, move.before);
    return;
  }
  if (homes.size === 0) return;
  // Top first, so each label's home is in place when the one under it goes back.
  for (const id of RIDE_LABEL_LAYERS.slice().reverse()) {
    const home = homes.get(id);
    if (!map.getLayer(id) || !homes.has(id) || (home !== undefined && !map.getLayer(home))) continue;
    map.moveLayer(id, home);
  }
  homes.clear();
}
