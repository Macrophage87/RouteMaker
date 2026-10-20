#!/usr/bin/env node
// Write frontend/src/fonts/map-glyphs/atkinson-next-semibold-<range>.pbf: the street names' glyphs
// (frontend/src/lib/mapGlyphs.ts), made from Atkinson Hyperlegible Next (SIL Open Font License,
// frontend/src/fonts/map-glyphs/OFL.txt) at weight 600. Run on a developer's machine only; nothing in
// the build or the deploy runs it. It needs fontnik (the glyph maker MapLibre's base maps use) and a
// static SemiBold instance of the variable font, made with fontTools, and the base map's Noto Sans Medium
// glyphs for the same ranges (scripts/fetch_basemap.sh ASSETS_COMMIT, fonts/Noto Sans Medium/):
//
//   curl -LO "https://raw.githubusercontent.com/google/fonts/main/ofl/atkinsonhyperlegiblenext/AtkinsonHyperlegibleNext%5Bwght%5D.ttf"
//   python3 -m fontTools.varLib.instancer "AtkinsonHyperlegibleNext[wght].ttf" wght=600 -o next-600.ttf
//   npm install --no-save fontnik@0.7.7 && node scripts/make_map_glyphs.mjs next-600.ttf "<basemap>/fonts/Noto Sans Medium"
//
// The font has only part of these ranges (94 of 256 code points in 256-511, 19 in 8192-8447), and MapLibre
// draws nothing for a code point missing from a range file it has, so each file is the font's glyphs with
// Noto Sans Medium's filling the rest (fontnik's composite: the first font wins): a name with "ō" or "‑"
// is still drawn whole.
//
// The variable font used (Version 2.001) had sha256
// 5a455d1cfa099b601ab70751bb9673e8fe1854dc4500c80e1a220d0d75e31745; docs/SOURCES.md has the outputs'.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const fontnik = createRequire(import.meta.url)("fontnik");
const RANGES = ["0-255", "256-511", "8192-8447"]; // lib/mapGlyphs.ts MAP_LABEL_RANGES
const out = fileURLToPath(new URL("../frontend/src/fonts/map-glyphs/", import.meta.url));
const font = readFileSync(process.argv[2]);
const noto = process.argv[3];
const call = (fn, arg) => new Promise((done, fail) => fn(arg, (e, data) => (e ? fail(e) : done(data))));
for (const range of RANGES) {
  const [start, end] = range.split("-").map(Number);
  const own = await call(fontnik.range, { font, start, end });
  const pbf = await call(fontnik.composite, [own, readFileSync(`${noto}/${range}.pbf`)]);
  writeFileSync(`${out}atkinson-next-semibold-${range}.pbf`, pbf);
  console.log(range, pbf.length);
}
