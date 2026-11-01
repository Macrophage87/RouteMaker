/**
 * The overlay layers' dark-map paint (the owner, 2026-11-01: battery audit). The base map is the Protomaps dark
 * flavour in the dark theme and in a ride or Roam after civil dusk (lib/mapFlavour.ts). The overlays' light-map paint
 * stays exactly as it is; a layer whose colour is under 3:1 on the dark map, or reads the wrong way there (a grey
 * mask that lightens what is outside), has its dark-map paint here, keyed by layer id, set while the dark map shows
 * and put back after (applyDarkPaint). darkMap.test.ts holds every colour to 3:1 on the dark surfaces.
 *
 * The stress tiers, the faint edges, the mountain-bike ticks and the route's casing follow by the palette's repaint
 * instead (stressStyle.js DARK_MAP, routeColours.ts casingOnMap), as they are built from the tiers.
 */
import { darkMapOn } from "../stressStyle.js";

/** The Scenic casing's dark-map teal: 3:1 or more on every dark surface, and still no stress, rail or route colour. */
export const SCENIC_DARK_COLOUR = "#2dd4bf";

/** The coverage and District masks darken what is outside on the dark map (a grey would lighten it), and their edges are light. */
export const MASK_DARK = "#000000";
export const MASK_EDGE_DARK = "#c3c8d0";

export const DARK_PAINT: Readonly<Record<string, Readonly<Record<string, unknown>>>> = {
  "coverage-mask": { "fill-color": MASK_DARK, "fill-opacity": 0.45 },
  "coverage-edge": { "line-color": MASK_EDGE_DARK },
  "massride-dc-mask": { "fill-color": MASK_DARK, "fill-opacity": 0.55 },
  "massride-dc-edge": { "line-color": MASK_EDGE_DARK },
  "scenic-casing": { "line-color": SCENIC_DARK_COLOUR },
  // A viewpoint is a white ring with a teal edge: the edge is what meets the map.
  "scenic-viewpoints": { "circle-stroke-color": SCENIC_DARK_COLOUR },
};

/** A layer as it is added now: its dark-map paint over its own while the dark map shows. */
export function withDarkPaint<T extends { id: string; paint?: object }>(layer: T, dark: boolean = darkMapOn()): T {
  const over = DARK_PAINT[layer.id];
  return dark && over ? { ...layer, paint: { ...layer.paint, ...over } } : layer;
}

/** The parts of a MapLibre map the repaint uses. */
export interface DarkPaintMap {
  getLayer(id: string): unknown;
  setPaintProperty(id: string, name: string, value: unknown): void;
}

/**
 * Paint every layer in DARK_PAINT that is on the map for the flavour: the dark values, or the light ones from
 * `light` (each layer's own definition, by id). A layer not yet added takes its paint when added (withDarkPaint).
 */
export function applyDarkPaint(map: DarkPaintMap, dark: boolean, light: ReadonlyArray<{ id: string; paint?: Record<string, unknown> }>): void {
  const byId = new Map(light.map((layer) => [layer.id, layer.paint ?? {}]));
  for (const [id, over] of Object.entries(DARK_PAINT)) {
    if (!map.getLayer(id)) continue;
    const own = byId.get(id);
    for (const name of Object.keys(over)) {
      const value = dark ? over[name] : own?.[name];
      if (value !== undefined) map.setPaintProperty(id, name, value);
    }
  }
}
