/**
 * THE DARK MAP. The owner, 2026-11-01: battery audit: the base map is the Protomaps dark flavour when the page is in
 * the dark theme, and in a ride or Roam between sunset and sunrise whatever the theme, to save screen power on
 * OLED phones (a dark pixel there is an unlit one). No control: it follows the theme and the light, as the panels
 * follow the theme (styles.css). It changes live, in place: the base map's layers keep their ids and layout between
 * the flavours (only their paint differs, flavour.test), so the paint is set again layer by layer and the sprite
 * swapped, and every overlay layer (the stress lines, the route, the dots, the stations) stays where it is. A
 * setStyle would rebuild the style and drop every layer added since load.
 *
 * The dark flavour is Protomaps' own, with this app's light-map changes made the same way (withClearRoadLabels:
 * the street names, state and county lines), and one change of its own: the background is the earth's colour, so
 * beyond the archive's edge is as dark as the land. The street and trail names take the dark flavour's label halo
 * with light text (stressStyle.js ROAD_LABEL), so they are not white bands on an unlit screen. The overlay's dark-map colours are in stressStyle.js (DARK_MAP),
 * routeColours.ts (casingOnMap), lib/darkPaint.ts and stationIcons.ts (OUTLINE_DARK_MAP); darkMap.test.ts holds
 * each one to 3:1 on the dark map's surfaces, as the light map's are held on its own.
 */
import { layers as protomapsLayers, namedFlavor, type Flavor } from "@protomaps/basemaps";
import { accessibilityOn, setDarkMap, withClearRoadLabels } from "../stressStyle.js";
import { BASEMAP_SOURCE_ID } from "./mapStyle.ts";
import { solarDay } from "./lightTimes.ts";
import { DARK_PAINT, applyDarkPaint, type DarkPaintMap, type PaintTable } from "./darkPaint.ts";
import { topoDarkPaint, topoLayers } from "./topoLines.ts";
import { CHOICE_CASING_LAYER, CHOICE_CASING_OPACITY } from "./routeChoice.ts";
import { COVERAGE_MASK_LAYERS } from "./mapGlue.ts";
import { DC_MASK_LAYERS } from "./dcBoundary.ts";
import { SCENIC_CASING_LAYER, SCENIC_COLOUR, scenicPointLayers } from "./scenicLayer.ts";

export type MapFlavour = "light" | "dark";

/** The flavour's colours: Protomaps' own, the dark one's background the earth's (above). */
export function flavourColours(flavour: MapFlavour): Flavor {
  const colours = namedFlavor(flavour);
  return flavour === "dark" ? { ...colours, background: colours.earth } : colours;
}

/** The base map's layers in a flavour, with this app's label and boundary changes (stressStyle.js). */
export function basemapLayers(flavour: MapFlavour, strong: boolean = accessibilityOn()): unknown[] {
  return withClearRoadLabels(protomapsLayers(BASEMAP_SOURCE_ID, flavourColours(flavour), { lang: "en" }), strong, flavour === "dark");
}

/**
 * Whether `ms` is between sunset and sunrise at `lat`, `lon` (lib/lightTimes.ts). Sunrise and sunset, not civil dawn
 * and dusk (the owner, 2026-11-01: "do sunrise/sunset").
 */
export function isDark(ms: number, lat: number, lon: number): boolean {
  const day = solarDay(ms, lat, lon);
  if (day.sunrise === null || day.sunset === null) return false;
  return ms < day.sunrise || ms >= day.sunset;
}

/** The next sunrise or sunset after `ms` (within two days), when the answer of isDark can next change; null if none. */
export function nextLightChange(ms: number, lat: number, lon: number): number | null {
  const DAY = 24 * 60 * 60_000;
  for (const at of [ms, ms + DAY, ms + 2 * DAY]) {
    const day = solarDay(at, lat, lon);
    const next = [day.sunrise, day.sunset].filter((t): t is number => t !== null && t > ms).sort((a, b) => a - b)[0];
    if (next !== undefined) return next;
  }
  return null;
}

/**
 * What decides the flavour. `onBike`: a ride or Roam (MapView's rideLabels). `at`: where the map is, [lon, lat].
 * `tunnel`: the rider is in a tunnel, or about to be (lib/tunnelDark.ts; the owner, 2026-11-01).
 */
export interface FlavourInputs {
  themeDark: boolean;
  onBike: boolean;
  now: number;
  at: readonly [number, number];
  tunnel?: boolean;
}

/** Dark in the dark theme, and on the bike between sunset and sunrise or in a tunnel; else light. */
export function mapFlavourFor({ themeDark, onBike, now, at, tunnel = false }: FlavourInputs): MapFlavour {
  return themeDark || (onBike && (tunnel || isDark(now, at[1], at[0]))) ? "dark" : "light";
}

/** The paint to set to go from one flavour's base layers to the other's: each property that differs, by layer id. */
export function basemapPaintChanges(from: readonly unknown[], to: readonly unknown[]): Array<{ id: string; name: string; value: unknown }> {
  type Layer = { id: string; paint?: Record<string, unknown> };
  const before = new Map((from as Layer[]).map((layer) => [layer.id, layer.paint ?? {}]));
  const out: Array<{ id: string; name: string; value: unknown }> = [];
  for (const layer of to as Layer[]) {
    const old = before.get(layer.id) ?? {};
    const paint = layer.paint ?? {};
    for (const name of new Set([...Object.keys(old), ...Object.keys(paint)])) {
      if (JSON.stringify(old[name]) !== JSON.stringify(paint[name])) out.push({ id: layer.id, name, value: paint[name] });
    }
  }
  return out;
}

/** The sprite for a flavour: Protomaps' sprites come in both (scripts/fetch_basemap.sh writes sprites/v4/<flavour>). */
export function spriteFor(origin: string, flavour: MapFlavour): string {
  return `${origin}/basemap/sprites/v4/${flavour}`;
}

/** The class on the page's root while the dark map shows: the map's focus ring turns light (styles.css). */
export const MAP_DARK_CLASS = "map-dark";

/** Every overlay layer's dark-map paint, by id: lib/darkPaint.ts's and the topo lines' (lib/topoLines.ts). */
export function overlayDarkPaint(): PaintTable {
  return { ...DARK_PAINT, ...topoDarkPaint() };
}

/** The light-map paint of the layers overlayDarkPaint paints for the dark map, to put back when the map turns light. */
export function overlayLightPaint(): Array<{ id: string; paint?: Record<string, unknown> }> {
  return [
    ...(COVERAGE_MASK_LAYERS as unknown as Array<{ id: string; paint: Record<string, unknown> }>),
    ...(DC_MASK_LAYERS as unknown as Array<{ id: string; paint: Record<string, unknown> }>),
    { id: SCENIC_CASING_LAYER, paint: { "line-color": SCENIC_COLOUR } },
    ...(scenicPointLayers(false) as Array<{ id: string; paint?: Record<string, unknown> }>),
    { id: CHOICE_CASING_LAYER, paint: { "line-opacity": CHOICE_CASING_OPACITY } },
    ...(topoLayers(true, false) as Array<{ id: string; paint?: Record<string, unknown> }>),
  ];
}

/** The parts of a MapLibre map the change uses. */
export interface FlavourMap extends DarkPaintMap {
  setSprite(url: string): unknown;
}

/**
 * Put the map in `to` from `from`, in place: the base map's paint and sprite, then the overlay's dark-map colours
 * (darkPaint.ts, and by the palette's repaint, which setDarkMap tells: the stress lines and the route's casing).
 * `overlayLight` is the light paint of darkPaint's layers, to put back.
 */
export function applyMapFlavour(
  map: FlavourMap,
  from: MapFlavour,
  to: MapFlavour,
  origin: string,
  overlayLight: ReadonlyArray<{ id: string; paint?: Record<string, unknown> }> = overlayLightPaint(),
  root: { classList: { toggle(name: string, on: boolean): unknown } } | null = typeof document === "undefined" ? null : document.documentElement,
): void {
  const dark = to === "dark";
  if (from !== to) {
    for (const { id, name, value } of basemapPaintChanges(basemapLayers(from), basemapLayers(to))) {
      if (map.getLayer(id)) map.setPaintProperty(id, name, value);
    }
    map.setSprite(spriteFor(origin, to));
  }
  root?.classList.toggle(MAP_DARK_CLASS, dark);
  setDarkMap(dark);
  applyDarkPaint(map, dark, overlayLight, overlayDarkPaint());
}
