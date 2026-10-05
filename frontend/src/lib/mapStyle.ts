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
import CREDITS_DATA from "./credits.json" with { type: "json" };
import { protocolUrl } from "./stressProtocol.ts";

export const BASEMAP_SOURCE_ID = "protomaps";
export const STRESS_SOURCE_ID = "stress";
export const SPRITE_FLAVOR = "light";
/** The zoom the map opens at, over central DC (MapView.tsx); the rail stations show from it. */
export const OPENING_ZOOM = 11.2;

/**
 * The credits every map view carries, brief, as an in-text citation is
 * (OWNER-DECISIONS 306, amending 301: "keep it brief and put the full information
 * in documentation"): short source names, from credits.json, which
 * tests/test_credits.py holds to the full references in docs/SOURCES.md (dataset,
 * publisher, licence, link, date). Every source a rider sees the work of is here,
 * whatever its licence asks (301):
 *
 * - OpenStreetMap, the base map, routing and place names (ODbL), and Protomaps,
 *   the base map's style and tiles;
 * - DC Open Data, one entry for every District layer used (DDOT traffic volume
 *   and the Central Business District, the Architect of the Capitol boundary, the
 *   Roadway Block, Metro stations and entrances, and the federal-land layers):
 *   CC BY 4.0 asks for the licence and that the data was changed, so both stay;
 * - VDOT traffic volume; Open Baltimore's streets and bike facilities;
 * - Montgomery County Planning Department's Bicycle LTS (its licence asks for
 *   that name);
 * - USGS 3DEP elevation, for the climb and the Hills slider; the U.S. Census
 *   Bureau's TIGER urban areas, which the stress tiers read; and Photon, the
 *   place search;
 * - Atkinson Hyperlegible, the panel's font (SIL OFL 1.1; OWNER-DECISIONS 384), whose
 *   full licence text is in the shipped licenses.txt.
 *
 * Comparison data used only inside the project is not shown anywhere
 * (credits.test.ts holds it absent).
 */
export const CREDITS: ReadonlyArray<{ text: string; html: string }> = CREDITS_DATA;

/** In the order the map shows them: OpenStreetMap first. */
export const MAP_CREDITS: readonly string[] = CREDITS.map((credit) => credit.html);

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
 * equal to these). The owner, 2026-09-29: "Zoom less than 12, show just bike
 * paths and the metro/MARC. 12 and 13, show LTS 3+, 14+ show show the quiet
 * streets." (OWNER-DECISIONS 73). Below `min` nothing is drawn; from `min`
 * only the traffic-free paths and trails; from `busy` the roads at LTS 3 and
 * above (BUSY_ROADS_MIN_ZOOM in core/stress_tiles.py); from `quiet` the quiet
 * streets and every segment (QUIET_STREETS_MIN_ZOOM). `max` is the source's
 * maxzoom: the deepest tile the map asks for, all of them drawn ahead after
 * each rebuild (core/tile_cache.py), and z15-16 are drawn from the z14 tile.
 */
export const STRESS_ZOOMS = { min: 10, busy: 12, quiet: 14, max: 14 } as const;
