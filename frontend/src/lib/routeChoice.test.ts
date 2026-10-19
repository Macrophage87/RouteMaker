/** Go's routes to choose from on the map (lib/routeChoice.ts; the owner, 2026-10-19). */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { RouteResponse } from "./api.ts";
import { candidateFieldset } from "./candidatePicker.ts";
import type { LonLat } from "./geo.ts";
import {
  CHOICE_DIRECT,
  CHOICE_OTHER,
  CHOICE_TRAILMAXXED,
  choiceColours,
  choiceFeatures,
  choiceLabel,
  choiceTradeoff,
  labelPoint,
} from "./routeChoice.ts";
import { routeCasing } from "./routeColours.ts";

function route(line: LonLat[], over: Partial<RouteResponse> & { s?: [number, number, number, number] } = {}): RouteResponse {
  const [one, two, three, four] = over.s ?? [3000, 2000, 1000, 0];
  return {
    preset: "default",
    variant: "standard",
    geometry: { type: "LineString", coordinates: line },
    distance_m: one + two + three + four,
    duration_s: 1800,
    climb_m: 20,
    descent_m: 20,
    stress_m: { "1": one, "2": two, "3": three, "4": four },
    attribution: [],
    ...over,
  } as RouteResponse;
}

const STRAIGHT: LonLat[] = [
  [-77.0, 38.9],
  [-77.0, 38.91],
  [-77.0, 38.92],
];
// Parts from the straight line in the middle, to the east.
const BOWED: LonLat[] = [
  [-77.0, 38.9],
  [-76.99, 38.91],
  [-77.0, 38.92],
];
const WEST: LonLat[] = [
  [-77.0, 38.9],
  [-77.02, 38.91],
  [-77.0, 38.92],
];

const OWN = route(STRAIGHT);
const DIRECT = { ...route(BOWED, { duration_s: 1500, s: [3000, 1034, 1966, 0] }), neighbour: { kind: "direct" as const, stress: 25, line: "" } };
const TRAIL = { ...route(WEST, { duration_s: 2100, s: [4448, 2000, 0, 0] }), neighbour: { kind: "calmer" as const, stress: 100, line: "" } };
const PICKED: RouteResponse = { ...OWN, candidates: [DIRECT, TRAIL] };

test("each route is told by its own colour: the rider's in the route's own, More direct and Trailmaxxed apart", () => {
  assert.deepEqual(choiceColours(PICKED), [routeCasing(), CHOICE_DIRECT, CHOICE_TRAILMAXXED]);
  const router = { ...OWN, candidates: [route(BOWED)] };
  assert.deepEqual(choiceColours(router), [routeCasing(), CHOICE_OTHER]);
  assert.equal(choiceColours(OWN), null, "one route: nothing to tell apart");
});

test("on the map each route says what it trades against the rider's own: time and miles of high stress, signed", () => {
  assert.equal(choiceTradeoff(DIRECT, OWN), "−5 min, +0.6 mi (1.0 km) high-stress");
  assert.equal(choiceTradeoff(TRAIL, OWN), "+5 min, −0.6 mi (1.0 km) high-stress");
  assert.equal(choiceTradeoff(route(BOWED, { duration_s: 1830 }), OWN), "about the same time and traffic");
  const routes = [PICKED, DIRECT, TRAIL];
  assert.equal(choiceLabel(routes, 0), "Your route, 30 min");
  assert.equal(choiceLabel(routes, 1), "More direct\n−5 min, +0.6 mi (1.0 km) high-stress");
  assert.equal(choiceLabel(routes, 2), "Trailmaxxed\n+5 min, −0.6 mi (1.0 km) high-stress");
});

test("the routes not chosen are drawn, every route is named, each where it parts from the others", () => {
  const data = choiceFeatures(PICKED, 0) as { features: { geometry: { type: string; coordinates: unknown }; properties: { index: number; color: string } }[] };
  const lines = data.features.filter((f) => f.geometry.type === "LineString");
  assert.deepEqual(lines.map((f) => [f.properties.index, f.properties.color]), [
    [1, CHOICE_DIRECT],
    [2, CHOICE_TRAILMAXXED],
  ]);
  const names = data.features.filter((f) => f.geometry.type === "Point");
  assert.deepEqual(names.map((f) => f.properties.index), [0, 1, 2]);
  assert.deepEqual(names[1].geometry.coordinates, BOWED[1], "More direct is named at its bow, away from the rest");
  // The chosen one is drawn as the route; the rider's own then joins the faint ones.
  const second = choiceFeatures(PICKED, 1) as typeof data;
  assert.deepEqual(second.features.filter((f) => f.geometry.type === "LineString").map((f) => f.properties.index), [0, 2]);
  assert.deepEqual(choiceFeatures(OWN, 0).features, [], "one route: nothing more to draw");
  assert.deepEqual(choiceFeatures(PICKED, 5).features, []);
  assert.equal(labelPoint([], STRAIGHT), null);
});

test("the route list carries the same colours as swatches the screen reader skips", () => {
  const html = renderToStaticMarkup(candidateFieldset("p", { answer: PICKED, choice: 0, onChoose: () => {}, colours: choiceColours(PICKED) }));
  assert.equal((html.match(/class="candidate-swatch"/g) ?? []).length, 3);
  assert.match(html, /class="candidate-swatch" aria-hidden="true" style="background:#0f766e"/);
  const plain = renderToStaticMarkup(candidateFieldset("p", { answer: PICKED, choice: 0, onChoose: () => {} }));
  assert.doesNotMatch(plain, /candidate-swatch/, "Plan: no swatches, the map draws one route");
});

test("App draws them in Go only, off the ride, and a press on one chooses it", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const choicesDrawn = mode === "go" && !riding && !reviewing && !stale && !planEdited && !aroundAvoid/);
  assert.match(app, /onPickRoute=\{choicesDrawn \? choose : undefined\}/);
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /queryRenderedFeatures\(box, \{ layers: \[CHOICE_LINE_LAYER\] \}\)/);
});
