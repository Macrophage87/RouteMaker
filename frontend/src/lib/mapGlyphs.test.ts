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
