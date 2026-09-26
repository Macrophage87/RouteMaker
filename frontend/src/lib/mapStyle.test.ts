import { test } from "node:test";
import assert from "node:assert/strict";
import { MAP_CREDITS, buildStyle, stressSource, STRESS_SOURCE_ID } from "./mapStyle.ts";

const ORIGIN = "https://routes.example.org";

test("every map carries both base map credits and the volume sources' credits", () => {
  const all = MAP_CREDITS.join(" ");
  assert.match(all, /OpenStreetMap contributors/);
  assert.match(all, /ODbL/);
  assert.match(all, /Protomaps/);
  assert.match(all, /District Department of Transportation|DDOT/);
  assert.match(all, /CC BY 4\.0/);
  assert.match(all, /Virginia Department of Transportation|VDOT/);
});

test("the base map source states its own credit, not the archive's half of it", () => {
  // The archive's embedded attribution names OpenStreetMap only.
  const style = buildStyle(ORIGIN, []);
  const source = style.sources.protomaps as { attribution?: string };
  assert.match(source.attribution ?? "", /OpenStreetMap/);
  assert.match(source.attribution ?? "", /Protomaps/);
});

test("everything the style loads comes from this site", () => {
  const style = buildStyle(ORIGIN, []);
  const urls = [style.glyphs, style.sprite, (style.sources.protomaps as { url: string }).url];
  for (const url of urls) {
    assert.ok(
      url.startsWith(`${ORIGIN}/basemap/`) || url.startsWith("pmtiles:///basemap/"),
      url,
    );
  }
  assert.ok(style.glyphs.includes("{fontstack}") && style.glyphs.includes("{range}"));
  assert.match(String(style.sprite), /\/sprites\/v4\/light$/);
});

test("the stress tiles are the contract's path, absolute, within its zooms", () => {
  const source = stressSource(ORIGIN);
  assert.deepEqual(source.tiles, [`${ORIGIN}/tiles/stress/{z}/{x}/{y}.pbf`]);
  assert.ok(source.minzoom >= 10);
  assert.ok(source.maxzoom <= 16);
  assert.equal(STRESS_SOURCE_ID.length > 0, true);
});

test("the base map layers are passed through untouched", () => {
  const layers = [{ id: "background", type: "background" }] as never[];
  assert.deepEqual(buildStyle(ORIGIN, layers).layers, layers);
});
