/**
 * Rail stations on the public map: the Metro's, coloured by line, and the
 * MARC Penn Line's as far as Baltimore Penn Station (owner, 2026-09-27).
 *
 * Plain data in, plain data out, so node --test runs all of it; railData.ts
 * feeds it the bundled fixtures (src/rail-data/README.md says where they come
 * from) and railLayer.ts puts the result on the map.
 */
import { MAX_POINTS, addPoint, haversineM, type LonLat } from "./geo.ts";

/** Metro's six lines, in the order a station's pie is drawn, and MARC's Penn Line. */
export const LINE_KEYS = ["red", "orange", "blue", "green", "yellow", "silver", "penn"] as const;
export type LineKey = (typeof LINE_KEYS)[number];
export type MetroLine = Exclude<LineKey, "penn">;

export interface LineStyle {
  key: LineKey;
  label: string;
  color: string;
}

/**
 * WMATA's published line colours (the Metro brand's Red, Orange, Blue, Green,
 * Yellow and Silver). The Penn Line's is PENN_COLOUR below.
 */
export const METRO_LINES: Record<MetroLine, LineStyle> = {
  red: { key: "red", label: "Red", color: "#bf0d3e" },
  orange: { key: "orange", label: "Orange", color: "#ed8b00" },
  blue: { key: "blue", label: "Blue", color: "#009cde" },
  green: { key: "green", label: "Green", color: "#00b140" },
  yellow: { key: "yellow", label: "Yellow", color: "#ffd100" },
  silver: { key: "silver", label: "Silver", color: "#919d9d" },
};

export const PENN_LABEL = "MARC Penn Line";

/**
 * The Penn Line's colour: a dark gold. The owner's choice (2026-09-28): "A
 * purple line will be opening soon, so a different color, gold maybe?" - the
 * OSM relation's own colour= tag, a pale lavender, would read as the Purple
 * Line's. #8a6500 is the lightest gold that stands 3:1 off every fill of the
 * base map a station is drawn over (the calmest is the scrub and park green,
 * 3.1:1), and 3.6:1 off Metro's Yellow, so the two never read as one.
 * stationIcons.test.ts measures both.
 */
export const PENN_COLOUR = "#8a6500";

/**
 * A LINE value as line keys, in drawing order, each once. Every value in the
 * committed layers is a comma list of the lines' full names in lower case, in
 * no fixed order and not always with a space ("green,yellow"); the README
 * beside the fixtures lists them. A word that is not a line's name throws, so
 * a refreshed layer that abbreviates ("grn") fails the tests rather than
 * drawing a station with a line missing.
 */
export function parseLines(value: string): MetroLine[] {
  const found = new Set<MetroLine>();
  for (const raw of value.split(",")) {
    const word = raw.trim().toLowerCase();
    if (word === "") continue;
    const line = Object.hasOwn(METRO_LINES, word) ? (word as MetroLine) : undefined;
    if (!line) throw new Error(`unknown Metro line ${JSON.stringify(raw.trim())} in ${JSON.stringify(value)}`);
    found.add(line);
  }
  if (found.size === 0) throw new Error(`no Metro line in ${JSON.stringify(value)}`);
  return LINE_KEYS.filter((key): key is MetroLine => found.has(key as MetroLine));
}

// The fixtures' shapes: GeoJSON FeatureCollections of points.
interface PointFeature<P> {
  geometry: { type: "Point"; coordinates: number[] } | null;
  properties: P;
}
export interface Collection<P> {
  features: PointFeature<P>[];
}
export interface MetroStationProps {
  NAME: string;
  LINE: string;
  GIS_ID: string;
}
export interface MetroEntranceProps {
  NAME: string;
  DESCRIPTION: string;
  GIS_ID: string;
}
export type MarcProps =
  | { kind: "station"; name: string; order: number; osm: string }
  | { kind: "elevator" | "entrance"; station: number; osm: string };
export interface MarcCollection extends Collection<MarcProps> {
  colour?: string | null;
}
/** metro-osm-elevators.geojson: OSM's elevators at stations DC lists none for. */
export interface OsmElevatorProps {
  station: string;
  station_gis_id: string;
  osm: string;
}
/** metro-line-corrections.json: lines DC's LINE field predates (README.md). */
export interface LineCorrections {
  changes: Array<{ add: string[]; since: string; source: string; stations: Array<[string, string]> }>;
}

export interface Station {
  id: string;
  name: string;
  point: LonLat;
  /** Metro lines serving it; empty for a MARC-only station. */
  metro: MetroLine[];
  /** Whether the MARC Penn Line calls here. */
  penn: boolean;
  /** DC's elevators, the bike entrance (owner, 2026-09-27). */
  elevators: LonLat[];
  /** OpenStreetMap's elevators: MARC's, and Metro's where DC lists none (owner, 2026-09-28). */
  osmElevators: LonLat[];
  /** Other entrances: stairs and escalators. */
  entrances: LonLat[];
}

/** A MARC station this close to a Metro station is the same place (Union Station, New Carrollton). */
export const SHARED_STATION_M = 250;
/** DC's entrance points are all well within this of their station; one further off is not trusted. */
export const ENTRANCE_REACH_M = 600;

function lonLat(feature: PointFeature<unknown>): LonLat | null {
  const c = feature.geometry?.coordinates;
  return c && c.length >= 2 && Number.isFinite(c[0]) && Number.isFinite(c[1]) ? [c[0], c[1]] : null;
}

function nearest(stations: readonly Station[], point: LonLat, within: number): Station | null {
  let best: Station | null = null;
  let bestM = within;
  for (const station of stations) {
    const m = haversineM(station.point, point);
    if (m <= bestM) {
      best = station;
      bestM = m;
    }
  }
  return best;
}

/**
 * Lines added to DC's LINE field for service it predates. Each correction
 * names its station by GIS_ID and by name, and both must match, so a
 * refreshed layer that renames or renumbers a station stops the build rather
 * than dropping the correction; a line the field already has is an error too,
 * because then the correction is spent and should go.
 */
export function applyCorrections(stations: Station[], corrections: LineCorrections): void {
  for (const change of corrections.changes) {
    const add = parseLines(change.add.join(","));
    for (const [name, gisId] of change.stations) {
      const station = stations.find((s) => s.id === `metro-${gisId}`);
      if (!station || station.name !== name) {
        throw new Error(`line correction for ${name} (${gisId}) matches no station in the layer`);
      }
      const already = add.filter((line) => station.metro.includes(line));
      if (already.length > 0) {
        throw new Error(`${name} already has ${already.join(", ")} in LINE: drop that correction`);
      }
      const lines = new Set([...station.metro, ...add]);
      station.metro = LINE_KEYS.filter((key): key is MetroLine => lines.has(key as MetroLine));
    }
  }
}

/**
 * One list of stations from the fixtures. DC's entrances are matched to
 * stations by position, not name (the two layers spell names differently);
 * MARC stations that stand at a Metro station become part of it; OSM's
 * elevators go to the station the fixture names, each once.
 */
export function buildStations(
  metro: Collection<MetroStationProps>,
  entrances: Collection<MetroEntranceProps>,
  marc: MarcCollection,
  extra: { corrections?: LineCorrections; osmElevators?: Collection<OsmElevatorProps> } = {},
): Station[] {
  const stations: Station[] = [];
  for (const feature of metro.features) {
    const point = lonLat(feature);
    if (!point) continue;
    const { NAME, LINE, GIS_ID } = feature.properties;
    stations.push({
      id: `metro-${GIS_ID}`,
      name: NAME,
      point,
      metro: parseLines(LINE),
      penn: false,
      elevators: [],
      osmElevators: [],
      entrances: [],
    });
  }
  if (extra.corrections) applyCorrections(stations, extra.corrections);
  const seenOsm = new Set<string>();
  const addOsmElevator = (station: Station, osm: string, point: LonLat) => {
    if (seenOsm.has(osm)) return;
    seenOsm.add(osm);
    station.osmElevators.push(point);
  };
  for (const feature of entrances.features) {
    const point = lonLat(feature);
    if (!point) continue;
    const station = nearest(stations, point, ENTRANCE_REACH_M);
    if (!station) continue;
    if (/elevator/i.test(feature.properties.DESCRIPTION)) station.elevators.push(point);
    else station.entrances.push(point);
  }
  const metroCount = stations.length;
  const byOrder = new Map<number, Station>();
  for (const feature of marc.features) {
    const props = feature.properties;
    const point = lonLat(feature);
    if (props.kind !== "station" || !point) continue;
    const shared = nearest(stations.slice(0, metroCount), point, SHARED_STATION_M);
    if (shared) {
      shared.penn = true;
      byOrder.set(props.order, shared);
    } else {
      const station: Station = {
        id: `marc-${props.osm.replace("/", "-")}`,
        name: props.name,
        point,
        metro: [],
        penn: true,
        elevators: [],
        osmElevators: [],
        entrances: [],
      };
      stations.push(station);
      byOrder.set(props.order, station);
    }
  }
  for (const feature of marc.features) {
    const props = feature.properties;
    const point = lonLat(feature);
    if (props.kind === "station" || !point) continue;
    const station = byOrder.get(props.station);
    if (!station) continue;
    if (props.kind === "elevator") addOsmElevator(station, props.osm, point);
    else station.entrances.push(point);
  }
  for (const feature of extra.osmElevators?.features ?? []) {
    const point = lonLat(feature);
    const station = stations.find((s) => s.id === `metro-${feature.properties.station_gis_id}`);
    if (!point || !station) continue;
    addOsmElevator(station, feature.properties.osm, point);
  }
  return stations;
}

export interface RailVisibility {
  metro: boolean;
  marc: boolean;
}

/** The lines a station shows with the toggles as they are, in drawing order. */
export function visibleLines(station: Station, visibility: RailVisibility): LineKey[] {
  return [...(visibility.metro ? station.metro : []), ...(visibility.marc && station.penn ? (["penn"] as const) : [])];
}

/** The name of the icon for a set of lines; one icon per combination on the map. */
export function iconId(lines: readonly LineKey[]): string {
  return `rail-${lines.join("-")}`;
}

/** A closed station's icon: grey, struck through, in its usual shape. */
export function closedIconId(shape: "circle" | "square"): string {
  return `rail-closed-${shape}`;
}

/** The icon's shape: a Metro station is round, a MARC-only one square, so the systems differ by more than colour. */
export function iconShape(lines: readonly LineKey[]): "circle" | "square" {
  return lines.every((line) => line === "penn") ? "square" : "circle";
}

export function lineStyle(line: LineKey, pennColor: string): LineStyle {
  return line === "penn" ? { key: "penn", label: PENN_LABEL, color: pennColor } : METRO_LINES[line];
}

/** "Red, Orange and Silver lines", "MARC Penn Line", "Red line, plus MARC Penn Line". */
export function linesLabel(lines: readonly LineKey[]): string {
  const metro = lines.filter((line) => line !== "penn").map((line) => METRO_LINES[line as MetroLine].label);
  const parts: string[] = [];
  if (metro.length > 0) {
    const list = metro.length === 1 ? metro[0] : `${metro.slice(0, -1).join(", ")} and ${metro[metro.length - 1]}`;
    parts.push(`${list} line${metro.length === 1 ? "" : "s"}`);
  }
  if (lines.includes("penn")) parts.push(PENN_LABEL);
  return parts.join(", plus ");
}

export interface BikeEntrance {
  point: LonLat;
  /**
   * Which it is: DC's elevator, OSM's elevator, DC's (or OSM's) other entrance, the station itself, or for a rider
   * on foot the nearest way in of any kind (walkEntrance).
   */
  kind: "elevator" | "osm-elevator" | "entrance" | "station" | "walk";
}

function nearestTo(from: LonLat, points: readonly LonLat[]): LonLat | null {
  let best: LonLat | null = null;
  let bestM = Number.POSITIVE_INFINITY;
  for (const point of points) {
    const m = haversineM(from, point);
    if (m < bestM) {
      best = point;
      bestM = m;
    }
  }
  return best;
}

/**
 * The ways in a ride with a bike may use at this station, best kind first: DC's elevators (owner, 2026-09-27: the
 * elevator is where a bike gets in); where DC lists none, OpenStreetMap's; where neither has one, the other entrances
 * (owner, 2026-09-28). Empty when nothing is known.
 */
export function bikeWaysIn(station: Station): { kind: BikeEntrance["kind"]; points: readonly LonLat[] } {
  const candidates: Array<[BikeEntrance["kind"], readonly LonLat[]]> = [
    ["elevator", station.elevators],
    ["osm-elevator", station.osmElevators],
    ["entrance", station.entrances],
  ];
  for (const [kind, points] of candidates) {
    if (points.length > 0) return { kind, points };
  }
  return { kind: "station", points: [] };
}

/**
 * Where a ride starting or ending at this station goes with a bike: one of its ways in (bikeWaysIn), the one nearest
 * `from`, where the rider comes from (Stephen 2026-10-20, at Shady Grove: "Somehow it missed one of the metro
 * entrances"), else the one nearest the station's own point; the station itself only when nothing is known. App then
 * asks the router which is quickest to reach (lib/stationWayIn.ts), since the nearest in a straight line can be
 * across the tracks.
 */
export function bikeEntrance(station: Station, from: LonLat | null = null): BikeEntrance {
  const ways = bikeWaysIn(station);
  const point = nearestTo(from ?? station.point, ways.points);
  return point ? { point, kind: ways.kind } : { point: station.point, kind: "station" };
}

/**
 * Where a rider on foot goes in (Stephen 2026-10-19: "if on walk mode, you can route people to the main entrance on
 * the metro"): any way in, stairs, escalator or elevator, the one nearest `from` (where they come from), else the one
 * nearest the station's own point. A station with none listed is the station itself.
 */
export function walkEntrance(station: Station, from: LonLat | null = null): BikeEntrance {
  const point = nearestTo(from ?? station.point, [...station.entrances, ...station.elevators, ...station.osmElevators]);
  return point ? { point, kind: "walk" } : { point: station.point, kind: "station" };
}

/** A station's way in for this ride: on foot (endsOnFoot), the nearest of any kind; with a bike, its nearest elevator. */
export function stationEntrance(station: Station, onFoot: boolean, from: LonLat | null = null): BikeEntrance {
  return onFoot ? walkEntrance(station, from) : bikeEntrance(station, from);
}

/** A point this close to one of a station's ways in is at that station (a shared link keeps 5 decimals, about 1 m). */
export const AT_ENTRANCE_M = 3;

/** A point of the plan moved to its station's way in for the new ride type (stationMoves). */
export interface StationMove {
  index: number;
  station: Station;
  /** The way in for the new ride: a new pair, never the station data's own, so marks on it stay the point's. */
  to: LonLat;
  kind: BikeEntrance["kind"];
}

/**
 * The points placed at a station that move to the station's way in for this ride (Stephen 2026-10-19, a station
 * picked on Bikeshare must not keep a bike at the stairs on the next ride type): on foot its nearest entrance (from
 * the next point for a start, else from the start, as App's walkFrom), with a bike its elevator. Empty when none.
 */
export function stationMoves(points: readonly LonLat[], stations: readonly Station[], onFoot: boolean): StationMove[] {
  const moves: StationMove[] = [];
  points.forEach((point, index) => {
    const station = stations.find((s) =>
      [...s.elevators, ...s.osmElevators, ...s.entrances].some((way) => haversineM(way, point) <= AT_ENTRANCE_M),
    );
    if (!station) return;
    const from = index === 0 ? (points[1] ?? null) : points[0];
    const way = stationEntrance(station, onFoot, from);
    if (haversineM(way.point, point) > AT_ENTRANCE_M) moves.push({ index, station, to: [way.point[0], way.point[1]], kind: way.kind });
  });
  return moves;
}

/** What a station's card says about where routes to it go. */
export function entranceNote(kind: BikeEntrance["kind"]): string {
  switch (kind) {
    case "elevator":
      return "Routes use its elevator, the way in with a bike.";
    case "osm-elevator":
      return "Routes use its elevator, from OpenStreetMap: DC's list has none here.";
    case "entrance":
      return "No elevator listed; routes use its nearest entrance.";
    case "station":
      return "No elevator or entrance listed; routes use the station itself.";
    case "walk":
      return "On foot, routes use its nearest entrance.";
  }
}

/**
 * The name a plan point placed at a station carries, rather than the street
 * its bike entrance is on (PLAN.md, the stationBikeEntrance naming): "Federal
 * Triangle Metro station", as the nearest-stations list says it; a MARC-only
 * station "Odenton MARC station"; a station whose own name already ends in
 * "Station" just that ("Union Station", not "Union Station Metro station").
 */
export function stationPlaceName(station: Pick<Station, "name" | "metro">): string {
  if (/\bstation$/i.test(station.name)) return station.name;
  return station.metro.length > 0 ? `${station.name} Metro station` : `${station.name} MARC station`;
}

/** The point's longer label: which way in it is, in words, so it is not only shown on the map. */
export function stationPlaceLabel(station: Pick<Station, "name" | "metro">, kind: BikeEntrance["kind"]): string {
  const name = stationPlaceName(station);
  switch (kind) {
    case "elevator":
    case "osm-elevator":
      return `${name}, at its elevator`;
    case "entrance":
    case "walk":
      return `${name}, at its nearest entrance`;
    case "station":
      return name;
  }
}

/**
 * A search result this close to a station, and tagged as a station, is that
 * station: OSM's station node can sit anywhere in its footprint, and the
 * shared MARC and Metro stations are already one within SHARED_STATION_M.
 */
export const STATION_MATCH_M = 300;

/**
 * The station a place search result is, or null: a railway or public
 * transport station (or halt) within STATION_MATCH_M of one of `stations`.
 * The search then puts the point at that station's bike entrance, as a tap
 * on the station does.
 */
export function stationForPlace(
  stations: readonly Station[],
  place: { lon: number; lat: number; osm_key?: string | null; osm_value?: string | null },
): Station | null {
  if (place.osm_key !== "railway" && place.osm_key !== "public_transport") return null;
  if (place.osm_value !== "station" && place.osm_value !== "halt") return null;
  return nearest(stations, [place.lon, place.lat], STATION_MATCH_M);
}

/** Stations by id, and the bike entrance by station id: what railData.ts exports. */
export function stationIndex(stations: readonly Station[]) {
  const byId = new Map(stations.map((station) => [station.id, station]));
  return {
    station: (id: string): Station | undefined => byId.get(id),
    /** Null for an id it does not know. */
    bikeEntrance: (id: string): LonLat | null => {
      const station = byId.get(id);
      return station ? bikeEntrance(station).point : null;
    },
  };
}

export interface StationFeatureProps {
  kind: "station";
  id: string;
  name: string;
  icon: string;
  /** Interchanges drawn over single-line stations where they touch. */
  sort: number;
  /** No service all day (railClosures.ts): struck through, greyed, and named "(closed)". */
  closed: boolean;
}
export interface EntranceFeatureProps {
  kind: "elevator" | "entrance";
  id: string;
  name: string;
}
/** A badge beside a station: a WMATA alert names it, or an elevator there is out (railClosures.ts). */
export interface BadgeFeatureProps {
  kind: "badge";
  id: string;
  name: string;
  icon: string;
  /** Pixels from the station's centre: the alert up and right, the elevator up and left. */
  offset: [number, number];
}
export interface RailFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: LonLat };
  properties: StationFeatureProps | EntranceFeatureProps | BadgeFeatureProps;
}

/** Which badges a station wears (the owner, 2026-10-18). */
export interface StationBadges {
  alert: boolean;
  elevatorOut: boolean;
}
export const ALERT_BADGE_ICON = "rail-badge-alert";
export const ELEVATOR_OUT_ICON = "rail-badge-elevator-out";
export const BADGE_OFFSET_PX = 10;

/** What the map's rail source holds for the toggles as they are. */
export function railFeatures(
  stations: readonly Station[],
  visibility: RailVisibility,
  isClosed: (station: Station) => boolean = () => false,
  badges: (station: Station) => StationBadges | null = () => null,
): { type: "FeatureCollection"; features: RailFeature[] } {
  const features: RailFeature[] = [];
  for (const station of stations) {
    const lines = visibleLines(station, visibility);
    if (lines.length === 0) continue;
    const closed = isClosed(station);
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: station.point },
      properties: {
        kind: "station",
        id: station.id,
        // Words as well as grey: "Union Station (closed)" (railClosures.ts).
        name: closed ? `${station.name} (closed)` : station.name,
        icon: closed ? closedIconId(iconShape(lines)) : iconId(lines),
        // An open station is drawn over a closed one beside it.
        sort: closed ? 0 : lines.length,
        closed,
      },
    });
    // WMATA's badges, on an open station shown with a Metro line: a closed one is struck through instead.
    const worn = closed || !lines.some((line) => line !== "penn") ? null : badges(station);
    for (const [on, icon, side] of [
      [worn?.alert, ALERT_BADGE_ICON, 1],
      [worn?.elevatorOut, ELEVATOR_OUT_ICON, -1],
    ] as const) {
      if (!on) continue;
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: station.point },
        properties: { kind: "badge", id: station.id, name: station.name, icon, offset: [side * BADGE_OFFSET_PX, -BADGE_OFFSET_PX] },
      });
    }
    for (const [kind, points] of [
      ["elevator", [...station.elevators, ...station.osmElevators]],
      ["entrance", station.entrances],
    ] as const) {
      for (const point of points) {
        features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: point },
          properties: { kind, id: station.id, name: station.name },
        });
      }
    }
  }
  return { type: "FeatureCollection", features };
}

/** Every icon any toggle setting can ask for, so all are made once, at load. */
export function allIconLines(stations: readonly Station[]): LineKey[][] {
  const seen = new Map<string, LineKey[]>();
  for (const visibility of [
    { metro: true, marc: true },
    { metro: true, marc: false },
    { metro: false, marc: true },
  ]) {
    for (const station of stations) {
      const lines = visibleLines(station, visibility);
      if (lines.length > 0) seen.set(iconId(lines), lines);
    }
  }
  return [...seen.values()];
}

export type StationRole = "start" | "end" | "via";

/** The roles a station can take in a plan of this many points. */
export function stationRoles(count: number, loop = false): StationRole[] {
  const roles: StationRole[] = ["start"];
  // A loop finishes at its start and has no end to set; a stop can follow the start alone (OWNER-DECISIONS 374).
  if (loop) {
    if (count >= 1 && count < MAX_POINTS) roles.push("via");
    return roles;
  }
  if (count >= 1) roles.push("end");
  if (count >= 2 && count < MAX_POINTS) roles.push("via");
  return roles;
}

/**
 * The plan with a station's point as its start, its end, or a via on the leg
 * it lengthens least. Start and end replace what was there; a lone start gets
 * the station as its end, or in a loop (which has no end) as its first stop.
 */
export function placeAtStation(points: readonly LonLat[], point: LonLat, role: StationRole, loop = false): LonLat[] {
  if (!stationRoles(points.length, loop).includes(role)) return [...points];
  if (role === "start") return points.length === 0 ? [point] : [point, ...points.slice(1)];
  if (role === "end") return points.length === 1 ? [points[0], point] : [...points.slice(0, -1), point];
  return addPoint(points, point, loop);
}

/** A station's Start here / End here / Add as stop as an edit of the plan, or why it is not one. */
export type StationEdit = { next: LonLat[]; index: number } | { refused: "cap" | "role" };

/**
 * The plan after a station's action, and the index of the point it set - by
 * its role, not by looking the point up, since the same station can be both
 * ends. A via the 25-point cap leaves no room for is refused as "cap"; a role
 * the plan does not offer (a card opened for fewer points) as "role".
 */
export function stationEdit(points: readonly LonLat[], point: LonLat, role: StationRole, loop = false): StationEdit {
  if (!stationRoles(points.length, loop).includes(role)) {
    return { refused: role === "via" && points.length >= MAX_POINTS ? "cap" : "role" };
  }
  const next = placeAtStation(points, point, role, loop);
  const index = role === "start" ? 0 : role === "end" ? next.length - 1 : next.indexOf(point, 1);
  return { next, index };
}
