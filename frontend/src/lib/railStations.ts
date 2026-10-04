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
  /** Which it is: DC's elevator, OSM's elevator, DC's (or OSM's) other entrance, or the station itself. */
  kind: "elevator" | "osm-elevator" | "entrance" | "station";
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
 * Where a ride starting or ending at this station goes: the elevator nearest
 * the station, which is where a bike gets in (owner, 2026-09-27). DC's
 * elevator first; where DC lists none, OpenStreetMap's; where neither has
 * one, the nearest other entrance (owner, 2026-09-28); the station itself
 * only when nothing is known.
 */
export function bikeEntrance(station: Station): BikeEntrance {
  const candidates: Array<[BikeEntrance["kind"], readonly LonLat[]]> = [
    ["elevator", station.elevators],
    ["osm-elevator", station.osmElevators],
    ["entrance", station.entrances],
  ];
  for (const [kind, points] of candidates) {
    const point = nearestTo(station.point, points);
    if (point) return { point, kind };
  }
  return { point: station.point, kind: "station" };
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
  }
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
}
export interface EntranceFeatureProps {
  kind: "elevator" | "entrance";
  id: string;
  name: string;
}
export interface RailFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: LonLat };
  properties: StationFeatureProps | EntranceFeatureProps;
}

/** What the map's rail source holds for the toggles as they are. */
export function railFeatures(
  stations: readonly Station[],
  visibility: RailVisibility,
): { type: "FeatureCollection"; features: RailFeature[] } {
  const features: RailFeature[] = [];
  for (const station of stations) {
    const lines = visibleLines(station, visibility);
    if (lines.length === 0) continue;
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: station.point },
      properties: {
        kind: "station",
        id: station.id,
        name: station.name,
        icon: iconId(lines),
        sort: lines.length,
      },
    });
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
 * the station as its end.
 */
export function placeAtStation(points: readonly LonLat[], point: LonLat, role: StationRole, loop = false): LonLat[] {
  if (!stationRoles(points.length, loop).includes(role)) return [...points];
  if (role === "start") return points.length === 0 ? [point] : [point, ...points.slice(1)];
  if (role === "end") return points.length === 1 ? [points[0], point] : [...points.slice(0, -1), point];
  return addPoint(points, point, loop);
}

/** A station's Start here / End here / Add as via as an edit of the plan, or why it is not one. */
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
