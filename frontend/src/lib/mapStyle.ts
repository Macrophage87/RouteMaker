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
import { protocolUrl } from "./stressProtocol.ts";

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
 * The stress overlay's source. The tiles are fetched through the stress
 * protocol (stressProtocol.ts), which asks again for a tile the API asks to be
 * fetched again; the URL it carries is absolute, the contract's path.
 */
export function stressSource(origin: string) {
  return {
    type: "vector" as const,
    tiles: [protocolUrl(`${origin}/tiles/stress/{z}/{x}/{y}.pbf`)],
    minzoom: STRESS_ZOOMS.min,
    maxzoom: STRESS_ZOOMS.max,
  };
}

/**
 * The zooms the stress tiles are drawn at, and where each level of detail
 * starts (core/stress_tiles.py, whose levels tests/test_stress_tiles.py holds
 * equal to these): below `min` nothing is drawn; from `min` only the
 * traffic-free paths (the owner, 2026-09-28: "Zoomed out just show the
 * trails."); from `roads` the roads' and streets' stress colours - the one the
 * owner may move, with ROAD_STRESS_MIN_ZOOM in core/stress_tiles.py; from
 * `full` footways and sidewalks too. `max` is the source's maxzoom: the
 * deepest tile the map asks for, all of them drawn ahead after each rebuild
 * (core/tile_cache.py), and z15-16 are drawn from the z14 tile.
 */
export const STRESS_ZOOMS = { min: 10, roads: 13, full: 14, max: 14 } as const;
