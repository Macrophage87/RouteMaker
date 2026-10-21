#!/usr/bin/env node
// Write frontend/src/fonts/map-glyphs/<name>-<range>.pbf: the map labels' glyphs (frontend/src/lib/mapGlyphs.ts),
// made from Atkinson Hyperlegible Next (SIL Open Font License, frontend/src/fonts/map-glyphs/OFL.txt): Regular
// (400) over Noto Sans Regular, SemiBold (600) and ExtraBold (800, the place names) over Noto Sans Medium (the base
// map has no Bold), and Italic (400) over Noto Sans Italic. Run on a developer's machine only; nothing in
// the build or the deploy runs it. It needs fontnik (the glyph maker MapLibre's base maps use) and a
// static instance of the variable font for each weight, made with fontTools, and the base map's matching Noto
// Sans glyphs for the same ranges (scripts/fetch_basemap.sh ASSETS_COMMIT, fonts/Noto Sans <face>/):
//
//   curl -LO "https://raw.githubusercontent.com/google/fonts/main/ofl/atkinsonhyperlegiblenext/AtkinsonHyperlegibleNext%5Bwght%5D.ttf"
//   curl -LO "https://raw.githubusercontent.com/google/fonts/main/ofl/atkinsonhyperlegiblenext/AtkinsonHyperlegibleNext-Italic%5Bwght%5D.ttf"
//   python3 -m fontTools.varLib.instancer "AtkinsonHyperlegibleNext[wght].ttf" wght=400 -o next-400.ttf
//   python3 -m fontTools.varLib.instancer "AtkinsonHyperlegibleNext[wght].ttf" wght=600 -o next-600.ttf
//   python3 -m fontTools.varLib.instancer "AtkinsonHyperlegibleNext[wght].ttf" wght=800 -o next-800.ttf
//   python3 -m fontTools.varLib.instancer "AtkinsonHyperlegibleNext-Italic[wght].ttf" wght=400 -o next-italic-400.ttf
//   npm install --no-save fontnik@0.7.7
//   node scripts/make_map_glyphs.mjs next-400.ttf "<basemap>/fonts/Noto Sans Regular" atkinson-next-regular
//   node scripts/make_map_glyphs.mjs next-600.ttf "<basemap>/fonts/Noto Sans Medium" atkinson-next-semibold
//   node scripts/make_map_glyphs.mjs next-800.ttf "<basemap>/fonts/Noto Sans Medium" atkinson-next-extrabold
//   node scripts/make_map_glyphs.mjs next-italic-400.ttf "<basemap>/fonts/Noto Sans Italic" atkinson-next-italic
//
// The font has only part of these ranges (94 of 256 code points in 256-511, 19 in 8192-8447), and MapLibre
// draws nothing for a code point missing from a range file it has, so each file is the font's glyphs with
// its Noto Sans face's filling the rest (fontnik's composite: the first font wins): a name with "ō" or "‑"
// is still drawn whole.
//
// The variable fonts used (Version 2.001) had sha256 5a455d1cfa099b601ab70751bb9673e8fe1854dc4500c80e1a220d0d75e31745
// (upright) and ce9cffed32742ad2d9238c561a93220385e5934cdc02b8eb4097a50efa957dc6 (italic); docs/SOURCES.md has
// the outputs'.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const fontnik = createRequire(import.meta.url)("fontnik");
const RANGES = ["0-255", "256-511", "8192-8447"]; // lib/mapGlyphs.ts MAP_LABEL_RANGES
const out = fileURLToPath(new URL("../frontend/src/fonts/map-glyphs/", import.meta.url));
const font = readFileSync(process.argv[2]);
const noto = process.argv[3];
const name = process.argv[4];
const call = (fn, arg) => new Promise((done, fail) => fn(arg, (e, data) => (e ? fail(e) : done(data))));
for (const range of RANGES) {
  const [start, end] = range.split("-").map(Number);
  const own = await call(fontnik.range, { font, start, end });
  const pbf = await call(fontnik.composite, [own, readFileSync(`${noto}/${range}.pbf`)]);
  writeFileSync(`${out}${name}-${range}.pbf`, pbf);
  console.log(range, pbf.length);
}
