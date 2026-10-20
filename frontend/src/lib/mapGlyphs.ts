/**
 * The map's label font (the owner, 2026-10-20: "yes, let's try the various forms of atkinson hyperlegible
 * next. I found it to actually be quite useful in general, as readability on bright screens or in the rain
 * is a great idea even for people with normal vision"; then, of the other map labels, "make the switch"):
 * every label on the map is drawn in Atkinson Hyperlegible Next.
 *
 * MapLibre draws text from glyph files (signed distance fields in protobuf, one per 256 code points), not
 * from a web font, and the style names one URL template for every font: the base map's, under
 * /basemap/fonts/ (scripts/fetch_basemap.sh). The three Latin ranges of each face below are made once from
 * the font with scripts/make_map_glyphs.mjs, with the base map's matching Noto Sans face filling the code
 * points the font lacks (MapLibre draws nothing for a code point missing from a range it has), and bundled
 * under src/fonts/map-glyphs/, so Vite serves them as hashed /assets/ files, which both edges already serve
 * and the service worker precaches; no edge, deploy or base map change is needed.
 *
 * The layers keep naming the base map's faces ("Noto Sans Medium" and so on, which every label layer and its
 * tests use), and MapView's transformRequest sends a glyph request for a face here to its bundled Atkinson
 * file: Regular for Noto Sans Regular, SemiBold for Noto Sans Medium (the weight the owner picked for the
 * street names), Italic for Noto Sans Italic. Any other range (a name in a script the font does not cover)
 * is left to the base map's Noto file, so such a name is still drawn. The street names name their face
 * outright (stressStyle.js, ROAD_LABEL).
 */
export const MAP_LABEL_FONT = "Atkinson Hyperlegible Next SemiBold";

/** The ranges bundled, corridor.ts GLYPH_RANGES: Basic Latin and Latin-1, Latin Extended-A and part of B, General Punctuation. */
export const MAP_LABEL_RANGES = ["0-255", "256-511", "8192-8447"] as const;

/** Each face drawn from the bundle: its files' stem, and the base map face for the ranges not bundled. */
export const MAP_FACES: Readonly<Record<string, { file: string; base: string }>> = {
  "Noto Sans Regular": { file: "atkinson-next-regular", base: "Noto Sans Regular" },
  "Noto Sans Medium": { file: "atkinson-next-semibold", base: "Noto Sans Medium" },
  "Noto Sans Italic": { file: "atkinson-next-italic", base: "Noto Sans Italic" },
  [MAP_LABEL_FONT]: { file: "atkinson-next-semibold", base: "Noto Sans Medium" },
};

/** The bundled files by stem and range ("atkinson-next-regular-0-255"), from Vite's glob of their URLs. */
export function bundledGlyphs(urls: Readonly<Record<string, string>>): Record<string, string> {
  return Object.fromEntries(Object.entries(urls).map(([path, url]) => [path.replace(/^.*\//, "").replace(/\.pbf$/, ""), url]));
}

/**
 * Where a glyph request goes: `bundled` is bundledGlyphs's table. A face or range not in it is left as it
 * is (undefined), except the street names' face, which the base map has not, so it goes to its Noto face.
 */
export function glyphRequestUrl(url: string, bundled: Readonly<Record<string, string>>): string | undefined {
  const match = /\/([^/]+)\/(\d+-\d+)\.pbf(?:\?.*)?$/.exec(url);
  const stack = match ? decodeURIComponent(match[1]) : "";
  const face = MAP_FACES[stack];
  if (!match || !face) return undefined;
  const range = match[2];
  const file = bundled[`${face.file}-${range}`];
  if (file) return new URL(file, url).href;
  if (stack === face.base) return undefined;
  return url.slice(0, match.index) + `/${encodeURIComponent(face.base)}/${range}.pbf`;
}

/** Whether a face's Latin ranges come with the app (precached), so a kept ride need not fetch them. */
export function bundledFace(stack: string): boolean {
  return stack in MAP_FACES;
}
