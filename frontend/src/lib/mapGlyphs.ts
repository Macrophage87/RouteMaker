/**
 * The map's own label font (the owner, 2026-10-20: "yes, let's try the various forms of atkinson
 * hyperlegible next. I found it to actually be quite useful in general, as readability on bright screens
 * or in the rain is a great idea even for people with normal vision"): the street names are set in
 * Atkinson Hyperlegible Next SemiBold (stressStyle.js, ROAD_LABEL).
 *
 * MapLibre draws text from glyph files (signed distance fields in protobuf, one per 256 code points),
 * not from a web font, and the style names one URL template for every font: the base map's, under
 * /basemap/fonts/ (scripts/fetch_basemap.sh). This font's three Latin ranges are made once from the
 * font with scripts/make_map_glyphs.mjs and bundled under src/fonts/map-glyphs/, so Vite serves them as
 * hashed /assets/ files, which both edges already serve and the service worker precaches; no edge,
 * deploy or base map change is needed. MapView's transformRequest sends a glyph request for this font
 * to the bundled file for its range, and any other range (a name in a script the font does not cover)
 * to the base map's Noto Sans Medium, so such a name is still drawn.
 */
export const MAP_LABEL_FONT = "Atkinson Hyperlegible Next SemiBold";

/** The face drawn for the ranges not bundled, which the base map's glyphs carry. */
export const MAP_LABEL_FALLBACK = "Noto Sans Medium";

/** The ranges bundled, corridor.ts GLYPH_RANGES: Basic Latin and Latin-1, Latin Extended-A and part of B, General Punctuation. */
export const MAP_LABEL_RANGES = ["0-255", "256-511", "8192-8447"] as const;

/**
 * Where a glyph request goes: `bundled` maps each bundled range to its asset URL. A request for another
 * font is left as it is (undefined).
 */
export function glyphRequestUrl(url: string, bundled: Readonly<Record<string, string>>): string | undefined {
  const match = /\/([^/]+)\/(\d+-\d+)\.pbf(?:\?.*)?$/.exec(url);
  if (!match || decodeURIComponent(match[1]) !== MAP_LABEL_FONT) return undefined;
  const range = match[2];
  if (bundled[range]) return new URL(bundled[range], url).href;
  return url.slice(0, match.index) + `/${encodeURIComponent(MAP_LABEL_FALLBACK)}/${range}.pbf`;
}
