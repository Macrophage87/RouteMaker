// A Mass Ride's route over the capacity map (Stephen, 2026-10-12: "The colors on mass ride are so
// bright that I can't see the actual route."): a white band inside a wider casing, over dimmed
// capacity roads (routeColours.ts, massRoutePaint).
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { MASS_AVOID, MASS_BANDS, MASS_LAYER_IDS } from "../massStyle.js";
import { contrastRatio } from "../stressStyle.js";
import {
  MASS_NETWORK_DIMMED,
  ROUTE_BLUE,
  ROUTE_CASING_CVD,
  ROUTE_CASING_WIDTH,
  ROUTE_HALO_EXTRA,
  ROUTE_MASS_BAND,
  ROUTE_MASS_BAND_WIDTH,
  ROUTE_MASS_CASING_WIDTH,
  massRoutePaint,
} from "./routeColours.ts";
import { ROUTE_MASS_BAND_LAYER_ID, ROUTE_STRESS_SOURCE_ID, setMassNetworkOpacity, setRouteSections } from "./mapGlue.ts";

const COORDS: Array<[number, number]> = [[-77.04, 38.9], [-77.02, 38.9], [-77.0, 38.9]];

function recordingMap(layers: string[]) {
  const paint: Record<string, unknown> = {};
  return {
    paint,
    map: {
      getLayer: (id: string) => (layers.includes(id) ? { id } : undefined),
      getSource: (id: string) => (id === ROUTE_STRESS_SOURCE_ID ? { setData: () => {} } : undefined),
      setPaintProperty: (id: string, name: string, value: unknown) => void (paint[`${id}.${name}`] = value),
    },
  };
}

const NETWORK = [...MASS_LAYER_IDS.casing, ...MASS_LAYER_IDS.line];

test("the band and casing are wider than every Mass Ride section's halo, with room for each", () => {
  const widestHalo = Math.max(...MASS_BANDS.map((b: { width: number }) => b.width), MASS_AVOID.width) + ROUTE_HALO_EXTRA;
  assert.ok((ROUTE_MASS_BAND_WIDTH - widestHalo) / 2 >= 2, "at least 2 px of white each side of the widest halo");
  assert.ok((ROUTE_MASS_CASING_WIDTH - ROUTE_MASS_BAND_WIDTH) / 2 >= 2, "at least 2 px of casing each side of the band");
  // Wider than any capacity road drawn under it, casing included, at its widest zoom (massStyle.js byZoom: z16 is as drawn).
  const widestRoad = Math.max(...MASS_BANDS.map((b: { width: number }) => b.width)) + 3;
  assert.ok(ROUTE_MASS_CASING_WIDTH >= widestRoad + 8, "the corridor stands at least 4 px proud of the widest road each side");
});

test("the casing is 3:1 from the white band in both palettes (WCAG 1.4.11)", () => {
  for (const casing of [ROUTE_BLUE, ROUTE_CASING_CVD]) assert.ok(contrastRatio(casing, ROUTE_MASS_BAND) >= 3, casing);
});

test("massRoutePaint: a capacity route gets the corridor and dims the roads; anything else is as before", () => {
  assert.deepEqual(massRoutePaint(true, false), { casingWidth: ROUTE_MASS_CASING_WIDTH, bandOpacity: 1, networkOpacity: MASS_NETWORK_DIMMED });
  assert.deepEqual(massRoutePaint(true, true), { casingWidth: ROUTE_MASS_CASING_WIDTH, bandOpacity: 0.45, networkOpacity: MASS_NETWORK_DIMMED });
  assert.deepEqual(massRoutePaint(false, false), { casingWidth: ROUTE_CASING_WIDTH, bandOpacity: 0, networkOpacity: 1 });
  assert.ok(MASS_NETWORK_DIMMED > 0.3 && MASS_NETWORK_DIMMED < 0.7, "dimmed, still readable");
});

test("setRouteSections: a Mass Ride route widens the casing, shows the band, dims the capacity roads; clearing it puts them back", () => {
  const { map, paint } = recordingMap(NETWORK);
  const mass = { geometry: { type: "LineString", coordinates: COORDS }, stress_spans: [{ from_m: 0, to_m: 3460, tier: 2, facility: "none", rpm: 150 }] };
  setRouteSections(map as never, mass as never, false);
  assert.equal(paint["route-casing.line-width"], ROUTE_MASS_CASING_WIDTH);
  assert.equal(paint[`${ROUTE_MASS_BAND_LAYER_ID}.line-opacity`], 1);
  for (const id of NETWORK) assert.equal(paint[`${id}.line-opacity`], MASS_NETWORK_DIMMED, id);
  // The Avoid roads and the hazard rails are warnings: not dimmed.
  assert.equal(paint[`${MASS_LAYER_IDS.avoid}.line-opacity`], undefined);
  setRouteSections(map as never, null, false);
  assert.equal(paint["route-casing.line-width"], ROUTE_CASING_WIDTH);
  assert.equal(paint[`${ROUTE_MASS_BAND_LAYER_ID}.line-opacity`], 0);
  for (const id of NETWORK) assert.equal(paint[`${id}.line-opacity`], 1, id);
});

test("setRouteSections: a stress route (no capacity figures) keeps the plain casing and full-strength roads", () => {
  const { map, paint } = recordingMap(NETWORK);
  setRouteSections(map as never, { geometry: { type: "LineString", coordinates: COORDS }, stress_spans: [{ from_m: 0, to_m: 3460, tier: 2, facility: "none" }] } as never, false);
  assert.equal(paint["route-casing.line-width"], ROUTE_CASING_WIDTH);
  assert.equal(paint[`${ROUTE_MASS_BAND_LAYER_ID}.line-opacity`], 0);
  for (const id of NETWORK) assert.equal(paint[`${id}.line-opacity`], 1, id);
});

test("setMassNetworkOpacity skips layers the map does not have yet", () => {
  const { map, paint } = recordingMap([]);
  setMassNetworkOpacity(map, MASS_NETWORK_DIMMED);
  assert.deepEqual(paint, {});
});

test("MapView adds the band between the casing and the sections, hidden until setRouteSections shows it, and dims an overlay added after the route", () => {
  const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  const at = (id: string) => mapView.indexOf(id);
  assert.ok(at('id: "route-casing"') < at("id: ROUTE_MASS_BAND_LAYER_ID") && at("id: ROUTE_MASS_BAND_LAYER_ID") < at('id: "route-ring"'));
  const band = mapView.slice(at("id: ROUTE_MASS_BAND_LAYER_ID"), at('id: "route-ring"'));
  assert.match(band, /"line-opacity": 0/);
  assert.match(mapView, /if \(added\) setMassNetworkOpacity\(map, massRoutePaint\(usesCapacity\(callbacks\.current\.route\?\.stress_spans\), false\)\.networkOpacity\)/);
});
