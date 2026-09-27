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
 * Yellow and Silver). The Penn Line's colour is not typed here: it is the
 * route relation's own colour= tag, carried in the MARC fixture.
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

export interface Station {
  id: string;
  name: string;
  point: LonLat;
  /** Metro lines serving it; empty for a MARC-only station. */
  metro: MetroLine[];
  /** Whether the MARC Penn Line calls here. */
  penn: boolean;
  /** Elevators, the bike entrance (owner, 2026-09-27). */
  elevators: LonLat[];
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
 * One list of stations from the three fixtures. DC's entrances are matched to
 * stations by position, not name (the two layers spell names differently);
 * MARC stations that stand at a Metro station become part of it.
 */
export function buildStations(
  metro: Collection<MetroStationProps>,
  entrances: Collection<MetroEntranceProps>,
  marc: MarcCollection,
): Station[] {
  const stations: Station[] = [];
  for (const feature of metro.features) {
    const point = lonLat(feature);
    if (!point) continue;
    const { NAME, LINE, GIS_ID } = feature.properties;
    stations.push({ id: `metro-${GIS_ID}`, name: NAME, point, metro: parseLines(LINE), penn: false, elevators: [], entrances: [] });
  }
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
    (props.kind === "elevator" ? station.elevators : station.entrances).push(point);
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

/** "Red, Orange and Silver lines", "MARC Penn Line", "Red line and MARC Penn Line". */
export function linesLabel(lines: readonly LineKey[]): string {
  const metro = lines.filter((line) => line !== "penn").map((line) => METRO_LINES[line as MetroLine].label);
  const parts: string[] = [];
  if (metro.length > 0) {
    const list = metro.length === 1 ? metro[0] : `${metro.slice(0, -1).join(", ")} and ${metro[metro.length - 1]}`;
    parts.push(`${list} line${metro.length === 1 ? "" : "s"}`);
  }
  if (lines.includes("penn")) parts.push(PENN_LABEL);
  return parts.join(" and ");
}

/**
 * Where a ride starting or ending at this station goes: its elevator nearest
 * the station, which is where a bike gets in (owner, 2026-09-27); the station
 * itself when none is known.
 */
export function bikeEntrance(station: Station): LonLat {
  let best: LonLat = station.point;
  let bestM = Number.POSITIVE_INFINITY;
  for (const elevator of station.elevators) {
    const m = haversineM(station.point, elevator);
    if (m < bestM) {
      best = elevator;
      bestM = m;
    }
  }
  return best;
}

export interface StationFeatureProps {
  kind: "station";
  id: string;
  name: string;
  lines: string;
  label: string;
  icon: string;
  /** Interchanges drawn over single-line stations where they touch. */
  sort: number;
  elevator: boolean;
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
        lines: lines.join(","),
        label: linesLabel(lines),
        icon: iconId(lines),
        sort: lines.length,
        elevator: station.elevators.length > 0,
      },
    });
    for (const [kind, points] of [
      ["elevator", station.elevators],
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
export function stationRoles(count: number): StationRole[] {
  const roles: StationRole[] = ["start"];
  if (count >= 1) roles.push("end");
  if (count >= 2 && count < MAX_POINTS) roles.push("via");
  return roles;
}

/**
 * The plan with a station's point as its start, its end, or a via on the leg
 * it lengthens least. Start and end replace what was there; a lone start gets
 * the station as its end.
 */
export function placeAtStation(points: readonly LonLat[], point: LonLat, role: StationRole): LonLat[] {
  if (!stationRoles(points.length).includes(role)) return [...points];
  if (role === "start") return points.length === 0 ? [point] : [point, ...points.slice(1)];
  if (role === "end") return points.length === 1 ? [points[0], point] : [...points.slice(0, -1), point];
  return addPoint(points, point);
}
