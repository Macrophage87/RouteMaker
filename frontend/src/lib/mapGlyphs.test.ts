// The map labels' bundled font (lib/mapGlyphs.ts): its glyph requests, and its files.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { MAP_FACES, MAP_LABEL_FONT, PLACE_LABEL_FONT, MAP_LABEL_RANGES, bundledFace, bundledGlyphs, glyphRequestUrl } from "./mapGlyphs.ts";
import { GLYPH_RANGES, fontStacks } from "./corridor.ts";
import { PLACE_LABEL, ROAD_LABEL, stressOverlayLayers, withClearRoadLabels } from "../stressStyle.js";

const DIR = new URL("../fonts/map-glyphs/", import.meta.url);
const STEMS = [...new Set(Object.values(MAP_FACES).map((f) => f.file))];
const FILES = STEMS.flatMap((stem) => MAP_LABEL_RANGES.map((range) => `${stem}-${range}`));
const BUNDLED = bundledGlyphs(Object.fromEntries(FILES.map((f) => [`./fonts/map-glyphs/${f}.pbf`, `/assets/${f}-hash.pbf`])));
const BASE = "https://example.org/basemap/fonts";

test("map glyphs: the street names' face is a bundled one", () => {
  assert.equal(ROAD_LABEL.font, MAP_LABEL_FONT);
  assert.ok(bundledFace(MAP_LABEL_FONT));
});

test("map glyphs: the place names' ExtraBold is bundled, its other ranges the base map's Noto Sans Medium", () => {
  assert.equal(PLACE_LABEL.font, PLACE_LABEL_FONT);
  assert.ok(bundledFace(PLACE_LABEL_FONT));
  assert.equal(glyphRequestUrl(`${BASE}/${encodeURIComponent(PLACE_LABEL_FONT)}/0-255.pbf`, BUNDLED), "https://example.org/assets/atkinson-next-extrabold-0-255-hash.pbf");
  assert.equal(glyphRequestUrl(`${BASE}/${encodeURIComponent(PLACE_LABEL_FONT)}/1024-1279.pbf`, BUNDLED), `${BASE}/Noto%20Sans%20Medium/1024-1279.pbf`);
});

test("map glyphs: each base map face's Latin ranges go to its Atkinson file, spaces raw or escaped", () => {
  assert.equal(glyphRequestUrl(`${BASE}/Noto Sans Regular/0-255.pbf`, BUNDLED), "https://example.org/assets/atkinson-next-regular-0-255-hash.pbf");
  assert.equal(glyphRequestUrl(`${BASE}/Noto%20Sans%20Medium/256-511.pbf`, BUNDLED), "https://example.org/assets/atkinson-next-semibold-256-511-hash.pbf");
  assert.equal(glyphRequestUrl(`${BASE}/Noto Sans Italic/8192-8447.pbf`, BUNDLED), "https://example.org/assets/atkinson-next-italic-8192-8447-hash.pbf");
  assert.equal(glyphRequestUrl(`${BASE}/${MAP_LABEL_FONT}/0-255.pbf`, BUNDLED), "https://example.org/assets/atkinson-next-semibold-0-255-hash.pbf");
});

test("map glyphs: another range stays the base map's, so a name in another script is still drawn", () => {
  assert.equal(glyphRequestUrl(`${BASE}/Noto Sans Medium/1024-1279.pbf`, BUNDLED), undefined);
  assert.equal(glyphRequestUrl(`${BASE}/${MAP_LABEL_FONT}/1024-1279.pbf`, BUNDLED), `${BASE}/Noto%20Sans%20Medium/1024-1279.pbf`);
});

test("map glyphs: any other face or file is left alone", () => {
  assert.equal(glyphRequestUrl(`${BASE}/Noto Sans Devanagari Regular v1/2304-2559.pbf`, BUNDLED), undefined);
  assert.equal(glyphRequestUrl("https://example.org/tiles/stress/1/2/3.pbf", BUNDLED), undefined);
});

test("map glyphs: every face of every map label is bundled: the base map's and the app's own", () => {
  const layers = [...withClearRoadLabels(protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" })), ...stressOverlayLayers("stress")];
  const stacks = new Set<string>();
  const walk = (v: unknown) => (typeof v === "string" ? /^(Noto Sans|Atkinson)/.test(v) && stacks.add(v) : Array.isArray(v) && v.forEach(walk));
  for (const l of layers as Array<{ layout?: Record<string, unknown> }>) walk(l.layout?.["text-font"]);
  for (const stack of stacks) if (!/Devanagari/.test(stack)) assert.ok(bundledFace(stack), stack);
  // The app's own label layers name these faces (lib/railLayer.ts and the rest), which the source checks below keep.
  for (const file of ["lib/railLayer.ts", "lib/trailMiles.ts", "lib/referenceLayer.ts", "lib/scenicLayer.ts", "lib/climbs.ts", "lib/topoLines.ts", "massStyle.js", "stressStyle.js"]) {
    const src = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
    for (const [, face] of src.matchAll(/"(Noto Sans [A-Za-z]+)"/g)) assert.ok(bundledFace(face), `${file}: ${face}`);
  }
});

test("map glyphs: the bundled files are the ones a kept ride needs, and no others", () => {
  assert.deepEqual([...MAP_LABEL_RANGES], [...GLYPH_RANGES]);
  const pbfs = readdirSync(DIR).filter((f) => f.endsWith(".pbf")).map((f) => f.replace(/\.pbf$/, "")).sort();
  assert.deepEqual(pbfs, [...FILES].sort());
  const ofl = readFileSync(new URL("OFL.txt", DIR), "utf8");
  assert.match(ofl, /Atkinson Hyperlegible Next Project Authors/);
  assert.match(ofl, /SIL OPEN FONT LICENSE Version 1\.1/);
});

/** The code points a glyph range file carries (the glyphs protobuf: fontstack 1 > glyph 3 > id 1). */
function codePoints(buf: Buffer): Set<number> {
  const ids = new Set<number>();
  const at = { i: 0 };
  const varint = () => {
    let value = 0;
    for (let shift = 0; ; shift += 7) {
      const byte = buf[at.i++];
      value += (byte & 127) * 2 ** shift;
      if (byte < 128) return value;
    }
  };
  const read = (end: number, depth: number) => {
    while (at.i < end) {
      const key = varint();
      if ((key & 7) === 0) {
        const value = varint();
        if (depth === 2 && key >> 3 === 1) ids.add(value);
        continue;
      }
      const stop = varint() + at.i;
      if ((depth === 0 && key >> 3 === 1) || (depth === 1 && key >> 3 === 3)) read(stop, depth + 1);
      at.i = stop;
    }
  };
  read(buf.length, 0);
  return ids;
}

test("map glyphs: each file carries every code point its base map face does, so no letter of a name is dropped", () => {
  // The base map's faces (basemaps-assets at fetch_basemap.sh's ASSETS_COMMIT), counted from their files;
  // the font alone has 189, 94 and 19 of the SemiBold's, for example.
  const want: Record<string, number[]> = {
    "atkinson-next-regular": [195, 256, 194],
    "atkinson-next-semibold": [193, 256, 194],
    "atkinson-next-extrabold": [193, 256, 194],
    "atkinson-next-italic": [193, 256, 186],
  };
  const sample = ["Street é ñ", "ō Ũ ŉ Ơ ư", "\u2010\u2011\u2032\u2033\u203c—’"];
  for (const stem of STEMS) {
    MAP_LABEL_RANGES.forEach((range, i) => {
      const ids = codePoints(readFileSync(new URL(`${stem}-${range}.pbf`, DIR)));
      assert.equal(ids.size, want[stem][i], `${stem} ${range}`);
      for (const ch of sample[i].replace(/ /g, "")) assert.ok(ids.has(ch.codePointAt(0)!), `${stem} ${range} ${ch}`);
    });
  }
});

test("map glyphs: the app's map and the share card send the glyph requests through glyphRequestUrl with every bundled file", () => {
  const assets = readFileSync(new URL("./mapGlyphAssets.ts", import.meta.url), "utf8");
  assert.match(assets, /const glyph = type === "Glyphs" \? glyphRequestUrl\(url, MAP_GLYPHS\) : undefined;/);
  assert.match(assets, /const MAP_GLYPHS = bundledGlyphs\(import\.meta\.glob<string>\("\.\.\/fonts\/map-glyphs\/\*\.pbf", \{ query: "\?url", import: "default", eager: true \}\)\);/);
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /transformRequest: mapGlyphRequest,/);
  assert.match(view, /fontStacks\(style\.layers\)\.filter\(\(stack\) => !bundledFace\(stack\)\)/);
  const card = readFileSync(new URL("../app/shareCardRender.ts", import.meta.url), "utf8");
  assert.match(card, /transformRequest: mapGlyphRequest,/);
});

test("map glyphs: the files are the ones docs/SOURCES.md records", () => {
  const sources = readFileSync(new URL("../../../docs/SOURCES.md", import.meta.url), "utf8");
  for (const name of [...FILES.map((f) => `${f}.pbf`), "OFL.txt"]) {
    const hash = createHash("sha256").update(readFileSync(new URL(name, DIR))).digest("hex");
    assert.ok(sources.includes(hash), `${name} ${hash}`);
  }
});

test("map glyphs: a kept ride asks the base map for none of the bundled faces (the service worker precaches them)", () => {
  const stacks = fontStacks(withClearRoadLabels(protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" })));
  assert.ok(!stacks.includes(MAP_LABEL_FONT), stacks.join());
  assert.deepEqual(stacks.filter((stack) => !bundledFace(stack)), []);
});
