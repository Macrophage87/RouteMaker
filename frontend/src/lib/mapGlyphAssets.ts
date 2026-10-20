/**
 * The bundled label glyphs (mapGlyphs.ts) as Vite serves them, and the transformRequest that sends a map's glyph
 * requests to them: the app's map (MapView.tsx) and the share card's (app/shareCardRender.ts) both use it, so every
 * map the app draws has the same labels. Vite only: the glob is compiled at build time.
 */
import type { RequestParameters, ResourceType } from "maplibre-gl";
import { bundledGlyphs, glyphRequestUrl } from "./mapGlyphs.ts";

export const MAP_GLYPHS = bundledGlyphs(import.meta.glob<string>("../fonts/map-glyphs/*.pbf", { query: "?url", import: "default", eager: true }));

export function mapGlyphRequest(url: string, type?: ResourceType): RequestParameters | undefined {
  const glyph = type === "Glyphs" ? glyphRequestUrl(url, MAP_GLYPHS) : undefined;
  return glyph ? { url: glyph } : undefined;
}
