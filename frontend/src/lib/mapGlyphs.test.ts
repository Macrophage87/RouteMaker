// The street names' bundled font (lib/mapGlyphs.ts): its glyph requests, and its files.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { MAP_LABEL_FALLBACK, MAP_LABEL_FONT, MAP_LABEL_RANGES, glyphRequestUrl } from "./mapGlyphs.ts";
import { GLYPH_RANGES, fontStacks } from "./corridor.ts";
import { ROAD_LABEL, withClearRoadLabels } from "../stressStyle.js";

const BUNDLED = { "0-255": "/assets/a-0.pbf", "256-511": "/assets/a-256.pbf", "8192-8447": "/assets/a-8192.pbf" };
const BASE = "https://example.org/basemap/fonts";

test("map glyphs: the street names' font is the bundled one", () => {
  assert.equal(ROAD_LABEL.font, MAP_LABEL_FONT);
});

test("map glyphs: a bundled range goes to its asset, spaces raw or escaped", () => {
  assert.equal(glyphRequestUrl(`${BASE}/${MAP_LABEL_FONT}/0-255.pbf`, BUNDLED), "https://example.org/assets/a-0.pbf");
  assert.equal(glyphRequestUrl(`${BASE}/${encodeURIComponent(MAP_LABEL_FONT)}/8192-8447.pbf`, BUNDLED), "https://example.org/assets/a-8192.pbf");
});

test("map glyphs: another range is the base map's fallback face, so a name in another script is still drawn", () => {
  assert.equal(glyphRequestUrl(`${BASE}/${MAP_LABEL_FONT}/1024-1279.pbf`, BUNDLED), `${BASE}/${encodeURIComponent(MAP_LABEL_FALLBACK)}/1024-1279.pbf`);
});

test("map glyphs: any other font is left alone", () => {
  assert.equal(glyphRequestUrl(`${BASE}/Noto Sans Regular/0-255.pbf`, BUNDLED), undefined);
  assert.equal(glyphRequestUrl("https://example.org/tiles/stress/1/2/3.pbf", BUNDLED), undefined);
});

test("map glyphs: the bundled ranges are the ones a kept ride needs, each a file", () => {
  assert.deepEqual([...MAP_LABEL_RANGES], [...GLYPH_RANGES]);
  for (const range of MAP_LABEL_RANGES) {
    const file = new URL(`../fonts/map-glyphs/atkinson-next-semibold-${range}.pbf`, import.meta.url);
    assert.ok(existsSync(file), range);
    assert.ok(readFileSync(file).length > 1000, range);
  }
  const ofl = readFileSync(new URL("../fonts/map-glyphs/OFL.txt", import.meta.url), "utf8");
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

test("map glyphs: each range carries every code point the base map's Noto Sans Medium does, so no letter of a name is dropped", () => {
  // The base map's Noto Sans Medium (basemaps-assets at fetch_basemap.sh's ASSETS_COMMIT) has 193, 256 and 194;
  // the font alone has 189, 94 and 19.
  const want: Record<string, number> = { "0-255": 193, "256-511": 256, "8192-8447": 194 };
  const sample: Record<string, string> = { "0-255": "Street é ñ", "256-511": "ō Ũ ŉ Ơ ư", "8192-8447": "\u2010\u2011\u2032\u2033\u203c—’" };
  for (const range of MAP_LABEL_RANGES) {
    const ids = codePoints(readFileSync(new URL(`../fonts/map-glyphs/atkinson-next-semibold-${range}.pbf`, import.meta.url)));
    assert.equal(ids.size, want[range], range);
    for (const ch of sample[range].replace(/ /g, "")) assert.ok(ids.has(ch.codePointAt(0)!), `${range} ${ch}`);
  }
});

test("map glyphs: MapView sends the glyph requests through glyphRequestUrl with the three bundled files", () => {
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /transformRequest: \(url, type\) => \{\s+const glyph = type === "Glyphs" \? glyphRequestUrl\(url, MAP_GLYPHS\) : undefined;/);
  for (const range of MAP_LABEL_RANGES) {
    assert.match(view, new RegExp(`from "\\./fonts/map-glyphs/atkinson-next-semibold-${range}\\.pbf\\?url";`));
    assert.match(view, new RegExp(`"${range}": atkinson`));
  }
});

test("map glyphs: the files are the ones docs/SOURCES.md records", () => {
  const sources = readFileSync(new URL("../../../docs/SOURCES.md", import.meta.url), "utf8");
  for (const name of [...MAP_LABEL_RANGES.map((r) => `atkinson-next-semibold-${r}.pbf`), "OFL.txt"]) {
    const hash = createHash("sha256").update(readFileSync(new URL(`../fonts/map-glyphs/${name}`, import.meta.url))).digest("hex");
    assert.ok(sources.includes(hash), `${name} ${hash}`);
  }
});

test("map glyphs: a kept ride does not ask the base map for the bundled font (the service worker precaches it)", () => {
  const stacks = fontStacks(withClearRoadLabels(protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" })));
  assert.ok(!stacks.includes(MAP_LABEL_FONT), stacks.join());
  assert.ok(stacks.includes(MAP_LABEL_FALLBACK), stacks.join());
});
