/**
 * The map's style: the self-hosted Protomaps base map under the stress overlay.
 *
 * Everything the style loads is on this site (PLAN.md, Base map): the archive
 * through the pmtiles protocol, glyphs and sprites from /basemap/, stress tiles
 * from the API. The base map layers themselves come from @protomaps/basemaps
 * and are passed in, so this module stays plain data that node --test can run
 * without the package installed.
 */
import { BASEMAP } from "../stressStyle.js";

export const BASEMAP_SOURCE_ID = "protomaps";
export const STRESS_SOURCE_ID = "stress";
export const SPRITE_FLAVOR = "light";
/** The zoom the map opens at, over central DC (MapView.tsx); the rail stations show from it. */
export const OPENING_ZOOM = 11.2;

/**
 * Credits every map view carries (the public-tier rules, owner decision
 * 2026-09-26; docs/OPERATIONS.md, "Licences, and the credits every map must
 * carry"). The base map's two are on its source; the traffic-volume sources
 * shape the stress colours and the route breakdown, so they are credited on
 * every view whether or not the overlay is showing.
 */
export const VOLUME_CREDITS: readonly string[] = [
  'Stress tiers use traffic volume from the District Department of Transportation (DDOT), adapted, ' +
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>',
  "Traffic volume: Virginia Department of Transportation (VDOT)",
];

/**
 * The rail stations' layers (src/rail-data/README.md). The MARC Penn Line's
 * stations are OpenStreetMap's and need nothing beyond the ODbL credit.
 */
export const RAIL_CREDITS: readonly string[] = [
  'Metro stations and entrances: District of Columbia (Open Data DC), ' +
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>',
];

/** In the order the map shows them: OpenStreetMap first. */
export const MAP_CREDITS: readonly string[] = [BASEMAP.attribution, ...VOLUME_CREDITS, ...RAIL_CREDITS];

/**
 * The attribution control's one entry. MapLibre sorts separate entries by
 * length (which put VDOT's first) and drops any entry that is part of a longer
 * one, so a single combined string keeps OpenStreetMap first and absorbs the
 * base map source's own copy of its credit. It ends with the third-party
 * licence notices the build ships (licenses.txt, written by Vite).
 */
export const MAP_ATTRIBUTION: string = [
  ...MAP_CREDITS,
  '<a href="/licenses.txt">Software licences</a>',
].join(" | ");

export interface BasemapStyle {
  version: 8;
  glyphs: string;
  sprite: string;
  sources: Record<string, unknown>;
  layers: unknown[];
}

export function buildStyle(origin: string, basemapLayers: readonly unknown[]): BasemapStyle {
  return {
    version: 8,
    // Absolute because MapLibre resolves glyph and sprite URLs itself; both are
    // fetched on the page's thread, so they carry the page as Referer.
    glyphs: `${origin}/basemap/fonts/{fontstack}/{range}.pbf`,
    sprite: `${origin}/basemap/sprites/v4/${SPRITE_FLAVOR}`,
    sources: {
      [BASEMAP_SOURCE_ID]: {
        type: "vector",
        url: BASEMAP.url,
        // Stated, because the archive's own attribution names only OSM.
        attribution: BASEMAP.attribution,
      },
    },
    layers: [...basemapLayers],
  };
}

/**
 * The stress overlay's source. Tile URLs are absolute because vector tiles are
 * fetched from MapLibre's workers, where a relative URL has no page to resolve
 * against.
 */
export function stressSource(origin: string) {
  return {
    type: "vector" as const,
    tiles: [`${origin}/tiles/stress/{z}/{x}/{y}.pbf`],
    minzoom: 10,
    maxzoom: 16,
  };
}
