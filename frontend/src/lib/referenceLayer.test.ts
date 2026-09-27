import { test } from "node:test";
import assert from "node:assert/strict";
import {
  REFERENCE_LAYER,
  REFERENCE_SOURCE,
  ROUTE_CASING_LAYER,
  showReference,
  type ReferenceMap,
} from "./referenceLayer.ts";
import type { LonLat } from "./geo.ts";

function fakeMap(layers: string[] = []) {
  const sources = new Map<string, object>();
  const order = [...layers];
  const map: ReferenceMap & { order: string[]; sources: Map<string, object> } = {
    order,
    sources,
    getSource: (id) => sources.get(id),
    addSource: (id, source) => {
      assert.ok(!sources.has(id), `source ${id} added twice`);
      sources.set(id, source);
    },
    removeSource: (id) => {
      assert.ok(!order.includes(REFERENCE_LAYER), "a source is removed only after its layer");
      sources.delete(id);
    },
    getLayer: (id) => (order.includes(id) ? { id } : undefined),
    addLayer: (layer, beforeId) => {
      const id = (layer as { id: string }).id;
      assert.ok(!order.includes(id), `layer ${id} added twice`);
      const at = beforeId ? order.indexOf(beforeId) : -1;
      if (at < 0) order.push(id);
      else order.splice(at, 0, id);
    },
    removeLayer: (id) => {
      order.splice(order.indexOf(id), 1);
    },
  };
  return map;
}

const LINE: LonLat[] = [
  [-77, 38.9],
  [-77.01, 38.91],
];

test("the file's line goes under the planned route", () => {
  const map = fakeMap(["roads", ROUTE_CASING_LAYER, "route-line"]);
  showReference(map, LINE);
  assert.deepEqual(map.order, ["roads", REFERENCE_LAYER, ROUTE_CASING_LAYER, "route-line"]);
  const data = (map.sources.get(REFERENCE_SOURCE) as { data: { geometry: { coordinates: LonLat[] } } }).data;
  assert.deepEqual(data.geometry.coordinates, LINE);
});

test("showing again replaces it, and null or a single point removes it", () => {
  const map = fakeMap([ROUTE_CASING_LAYER]);
  showReference(map, LINE);
  showReference(map, [...LINE, [-77.02, 38.92]]);
  assert.equal(map.order.filter((l) => l === REFERENCE_LAYER).length, 1);
  showReference(map, null);
  assert.equal(map.getLayer(REFERENCE_LAYER), undefined);
  assert.equal(map.getSource(REFERENCE_SOURCE), undefined);
  showReference(map, [LINE[0]]);
  assert.equal(map.getSource(REFERENCE_SOURCE), undefined);
});

test("without the route layers yet, it is added on top", () => {
  const map = fakeMap(["roads"]);
  showReference(map, LINE);
  assert.deepEqual(map.order, ["roads", REFERENCE_LAYER]);
});
