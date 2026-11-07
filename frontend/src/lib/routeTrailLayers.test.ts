import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ROUTE_TRAIL_LAYER_IDS, ROCK_EDGE_PX, ROCK_PX, ROCK_SPACING_PX, routeTrailFeatures, routeTrailLayers } from "./routeTrailLayers.ts";
import { TRAIL_ROCK } from "./trailRocks.ts";
import { ROUTE_LINE_WIDTH } from "./routeColours.ts";

// Stephen, 2026-11-07, of the ribbon's trail colours and rocks: "Put that on the main track too", "and map, makes it
// easy to tell you're on a mtb trail".
const route = {
  geometry: { type: "LineString" as const, coordinates: [[-77, 38.9], [-77, 38.91], [-77, 38.92]] as [number, number][] },
  distance_m: 2224,
  stress_spans: [{ from_m: 0, to_m: 2224, tier: 1, facility: "path" as const }],
  trail_levels: [
    { from_m: 0, to_m: 1112, level: 3 },
    { from_m: 1112, to_m: 2224, level: 0 },
    { from_m: 100, to_m: 200, level: 9 },
  ],
};

test("each trail stretch is a line along the route in its trail's colour, unrated in the unrated trails' brown", () => {
  const { features } = routeTrailFeatures(route as never);
  assert.deepEqual(
    features.map((f) => [f.properties.level, f.properties.color]),
    [
      [3, "#1c1917"],
      [0, "#7a5536"],
    ],
  );
  const first = features[0]!.geometry.coordinates;
  assert.ok(Math.abs(first[0]![1] - 38.9) < 1e-6 && Math.abs(first[first.length - 1]![1] - 38.91) < 1e-4);
  assert.deepEqual(routeTrailFeatures(null).features, []);
  assert.deepEqual(routeTrailFeatures({ ...route, trail_levels: null } as never).features, []);
});

test("the stones sit either side of the route's width, one spacing in both layers, the colour over the route", () => {
  const [edge, stones, colour] = routeTrailLayers() as { id: string; paint: Record<string, unknown> }[];
  assert.deepEqual([edge!.id, stones!.id, colour!.id], [...ROUTE_TRAIL_LAYER_IDS]);
  assert.equal(edge!.paint["line-gap-width"], ROUTE_LINE_WIDTH);
  assert.equal(stones!.paint["line-color"], TRAIL_ROCK.fill);
  assert.deepEqual(edge!.paint["line-dasharray"], [0, ROCK_SPACING_PX / ROCK_EDGE_PX]);
  assert.deepEqual(stones!.paint["line-dasharray"], [0, ROCK_SPACING_PX / ROCK_PX]);
  assert.deepEqual(colour!.paint["line-color"], ["get", "color"]);
  // Drawn and kept current by the map, faded with the route's sections.
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /for \(const layer of routeTrailLayers\(\)\) map\.addLayer\(layer as never\);/);
  assert.match(map, /\?\.setData\(routeTrailFeatures\(stale \? null : route\) as never\);/);
  const glue = readFileSync(new URL("./mapGlue.ts", import.meta.url), "utf8");
  assert.match(glue, /for \(const id of ROUTE_TRAIL_LAYER_IDS\) if \(!map\.getLayer \|\| map\.getLayer\(id\)\) map\.setPaintProperty\(id, "line-opacity", paint\.sectionOpacity\);/);
});
