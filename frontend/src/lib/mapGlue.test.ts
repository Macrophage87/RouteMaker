// What MapView does to the map, run against a stand-in map that records calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addStressOverlay, hoverChanged, mapClickAction, markerDeps, setStressVisibility, type OverlayMap } from "./mapGlue.ts";
import { STRESS_SOURCE_ID, stressSource } from "./mapStyle.ts";
import { stressOverlayLayers } from "../stressStyle.js";

function fakeMap(styleLayers: Array<{ id: string; type: string }>) {
  const sources = new Map<string, unknown>();
  const added: Array<{ layer: { id: string; layout?: { visibility?: string } }; before: string | undefined }> = [];
  const layout: Array<[string, string, string]> = [];
  const map: OverlayMap = {
    getSource: (id) => sources.get(id),
    addSource: (id, source) => {
      sources.set(id, source);
    },
    getStyle: () => ({ layers: styleLayers }),
    addLayer: (layer, before) => {
      added.push({ layer: layer as (typeof added)[number]["layer"], before });
    },
    getLayer: (id) => added.find((a) => a.layer.id === id)?.layer,
    setLayoutProperty: (id, name, value) => {
      layout.push([id, name, value]);
    },
  };
  return { map, sources, added, layout };
}

const BASE = [
  { id: "water", type: "fill" },
  { id: "roads", type: "line" },
  { id: "road-labels", type: "symbol" },
  { id: "places", type: "symbol" },
];

test("the overlay is added exactly as stressOverlayLayers lists it, in its order", () => {
  const { map, added } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  const expected = stressOverlayLayers(STRESS_SOURCE_ID);
  assert.deepEqual(
    added.map((a) => a.layer.id),
    expected.map((l: { id: string }) => l.id),
  );
  for (const [i, layer] of expected.entries()) {
    const { layout, ...rest } = added[i].layer as Record<string, unknown>;
    assert.deepEqual(rest, layer, layer.id);
    assert.ok(layout);
  }
});

test("the overlay goes under the first label layer, all of it", () => {
  const { map, added } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  assert.ok(added.length > 0);
  for (const a of added) assert.equal(a.before, "road-labels");
});

test("the overlay is added with the toggle's visibility", () => {
  for (const [visible, visibility] of [
    [true, "visible"],
    [false, "none"],
  ] as const) {
    const { map, added } = fakeMap(BASE);
    addStressOverlay(map, "https://example.test", visible);
    for (const a of added) assert.equal(a.layer.layout?.visibility, visibility);
  }
});

test("the overlay reads the stress source, and is added once", () => {
  const { map, sources, added } = fakeMap(BASE);
  assert.equal(addStressOverlay(map, "https://example.test", true), true);
  assert.deepEqual(sources.get(STRESS_SOURCE_ID), stressSource("https://example.test"));
  const count = added.length;
  assert.equal(addStressOverlay(map, "https://example.test", true), false);
  assert.equal(added.length, count);
});

test("the toggle sets every overlay layer that is on the map", () => {
  const { map, layout } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  for (const [visible, visibility] of [
    [false, "none"],
    [true, "visible"],
  ] as const) {
    layout.length = 0;
    setStressVisibility(map, visible);
    assert.deepEqual(
      layout,
      stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => [l.id, "visibility", visibility]),
    );
  }
  const empty = fakeMap(BASE);
  setStressVisibility(empty.map, true);
  assert.equal(empty.layout.length, 0, "a layer not on the map was set");
});

test("the markers are placed again when markerReset changes, even with the same points", () => {
  // React re-runs an effect when any dependency is not Object.is the last.
  const changed = (a: readonly unknown[], b: readonly unknown[]) =>
    a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]));
  const points: Array<[number, number]> = [
    [-77, 38.9],
    [-76.9, 38.95],
  ];
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 0)), false);
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 1)), true, "a put-back leaves the markers");
  assert.equal(changed(markerDeps(points, 0), markerDeps([...points], 0)), true, "new points leave the markers");
});

test("a click that dismisses a via's Remove only dismisses it, on the line or off it", () => {
  for (const onLine of [false, true]) {
    for (const afterDrag of [false, true]) {
      assert.equal(mapClickAction({ popupOpen: true, afterDrag, onLine }), "close-popup");
    }
  }
});

test("the click at the end of a drag of the line adds nothing", () => {
  assert.equal(mapClickAction({ popupOpen: false, afterDrag: true, onLine: true }), "ignore");
  assert.equal(mapClickAction({ popupOpen: false, afterDrag: true, onLine: false }), "ignore");
});

test("otherwise a click on the line is a via in that leg, and elsewhere a new point", () => {
  assert.equal(mapClickAction({ popupOpen: false, afterDrag: false, onLine: true }), "line");
  assert.equal(mapClickAction({ popupOpen: false, afterDrag: false, onLine: false }), "point");
});

test("the hover handle is drawn again only when it appears, goes or moves", () => {
  assert.equal(hoverChanged(null, null), false, "still nowhere near the line");
  assert.equal(hoverChanged([-77, 38.9], [-77, 38.9]), false, "the same spot");
  assert.equal(hoverChanged(null, [-77, 38.9]), true);
  assert.equal(hoverChanged([-77, 38.9], null), true);
  assert.equal(hoverChanged([-77, 38.9], [-77.001, 38.9]), true);
  assert.equal(hoverChanged([-77, 38.9], [-77, 38.901]), true);
});
