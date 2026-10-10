/**
 * The Avoid-rated junction marker with its glyph (OWNER-DECISIONS 310): the Noto
 * Emoji skull and crossbones, bundled as text by Vite's ?raw import so it is inlined
 * in the page and nothing is fetched. Its source, sha256 and licence are recorded in
 * fixtures/icons/README.md and docs/SOURCES.md; its Apache 2.0 notice ships in
 * licenses.txt (src/licences/notices.mjs).
 */
import glyph from "../icons/noto-emoji-u2620.svg?raw";
import { AVOID_ICON_PX, avoidIconSvg } from "./avoidJunctions.ts";

export function avoidMarkerSvg(size = AVOID_ICON_PX): string {
  return avoidIconSvg(glyph, size);
}
