import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { ClosedStation } from "./api.ts";
import { MATCH_M, closedLabel, closedReason, closuresDayOf, matchClosures, requestClosures, serviceDayOf } from "./railClosures.ts";
import { railFeatures, closedIconId, type Station } from "./railStations.ts";
import { railImages, railLayers, RAIL_LAYERS } from "./railLayer.ts";
import { CLOSED_STRIKE, closedStationIcon, hexToRgb } from "./stationIcons.ts";
import { metroPlaces } from "./nearest.ts";

const SRC = new URL("../", import.meta.url);
const src = (path: string) => readFileSync(new URL(path, SRC), "utf8");

const station = (id: string, name: string, point: [number, number], metro: Station["metro"], penn: boolean): Station => ({
  id,
  name,
  point,
  metro,
  penn,
  elevators: [],
  osmElevators: [],
  entrances: [],
});
// Union Station: Metro's Red line and MARC's Penn Line; Odenton: MARC only; Eastern Market: Metro only.
const UNION = station("union", "Union Station", [-77.0063, 38.8973], ["red"], true);
const ODENTON = station("odenton", "Odenton", [-76.7, 39.085], [], true);
const EASTERN = station("eastern", "Eastern Market", [-76.996, 38.8846], ["orange", "blue", "silver"], false);
const STATIONS = [UNION, ODENTON, EASTERN];
const BOTH = { metro: true, marc: true };

const closed = (name: string, system: string, point: [number, number], reason: string): ClosedStation => ({
  name,
  system,
  lon: point[0],
  lat: point[1],
  reason,
});

test("a closure is matched to the nearest station of its own system, within reach", () => {
  const closures = matchClosures(STATIONS, [
    closed("Union Station MARC", "MARC", [-77.0055, 38.8968], "no MARC weekend service"),
    closed("Odenton", "MARC", [-76.7002, 39.0851], "no MARC weekend service"),
    // A Metro closure far from any Metro station is not drawn.
    closed("Nowhere", "Metro", [-76.5, 39.3], "no Metro service today"),
    // A system the map has no layer for is left out.
    closed("Camden Station", "Light RailLink", [-76.62, 39.28], "no Light RailLink service today"),
  ]);
  assert.equal(MATCH_M, 400);
  assert.deepEqual(closures.get("union"), { marc: "no MARC weekend service" });
  assert.deepEqual(closures.get("odenton"), { marc: "no MARC weekend service" });
  assert.equal(closures.size, 2);
});

test("a station two systems serve is closed only when every system it shows is", () => {
  const closures = matchClosures(STATIONS, [closed("Union Station MARC", "MARC", UNION.point, "no MARC weekend service")]);
  assert.equal(closedReason(UNION, BOTH, closures), null, "Metro still runs");
  // With Metro's stations hidden, the Union Station shown is MARC's: closed.
  assert.equal(closedReason(UNION, { metro: false, marc: true }, closures), "no MARC weekend service");
  assert.equal(closedReason(ODENTON, BOTH, matchClosures(STATIONS, [closed("Odenton", "MARC", ODENTON.point, "no MARC holiday service")])), "no MARC holiday service");
  const both = matchClosures(STATIONS, [
    closed("Union Station MARC", "MARC", UNION.point, "no MARC weekend service"),
    closed("Union Station", "Metro", UNION.point, "no Metro service today"),
  ]);
  assert.equal(closedReason(UNION, BOTH, both), "no Metro service today and no MARC weekend service");
  assert.equal(closedReason(EASTERN, BOTH, both), null);
  // A station not shown at all is not closed on the map.
  assert.equal(closedReason(ODENTON, { metro: true, marc: false }, both), null);
});

test("on the map a closed station is struck through, greyed and named '(closed)', so colour is not the only cue", () => {
  const closures = matchClosures(STATIONS, [closed("Odenton", "MARC", ODENTON.point, "no MARC weekend service")]);
  const features = railFeatures(STATIONS, BOTH, (s) => closedReason(s, BOTH, closures) !== null).features;
  const odenton = features.find((f) => f.properties.kind === "station" && f.properties.id === "odenton")!.properties;
  assert.equal(odenton.name, "Odenton (closed)");
  assert.equal(closedLabel("Odenton"), "Odenton (closed)");
  assert.equal(odenton.kind === "station" && odenton.icon, closedIconId("square"));
  assert.equal(odenton.kind === "station" && odenton.closed, true);
  const union = features.find((f) => f.properties.kind === "station" && f.properties.id === "union")!.properties;
  assert.equal(union.name, "Union Station");
  assert.equal(union.kind === "station" && union.closed, false);
  // Every closed icon is made at load, in each shape.
  const ids = railImages(STATIONS, "#8a6500", 1).map((image) => image.id);
  assert.ok(ids.includes("rail-closed-circle") && ids.includes("rail-closed-square"));
  // The name is greyed as well as worded.
  const names = railLayers().find((layer) => layer.id === RAIL_LAYERS.stations) as { paint: Record<string, unknown> };
  assert.deepEqual(names.paint["text-color"], ["case", ["==", ["get", "closed"], true], "#4b5563", "#1f2937"]);
});

test("the closed icon's centre is the strike, its edge grey", () => {
  const icon = closedStationIcon("circle", 1, 20);
  const pixel = (x: number, y: number) => Array.from(icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 4));
  assert.deepEqual(pixel(10, 10).slice(0, 3), hexToRgb(CLOSED_STRIKE));
  // Off the strike, inside the ring: the grey fill.
  assert.deepEqual(pixel(5, 5).slice(0, 3), hexToRgb("#d1d5db"));
  // A corner off the strike is transparent.
  assert.equal(pixel(0, 19)[3], 0);
});

test("the station's card and the nearest list say 'closed' in words", () => {
  const card = src("railInteraction.ts");
  assert.match(card, /name\.textContent = closed \? `\$\{station\.name\}, closed: \$\{closed\}` : station\.name;/);
  const places = metroPlaces([EASTERN], () => "no Metro service today");
  assert.equal(places[0].title, "Eastern Market Metro station, closed: no Metro service today");
  assert.equal(metroPlaces([EASTERN])[0].title, "Eastern Market Metro station");
});

test("the service day turns over at 3 am in Washington", () => {
  assert.equal(serviceDayOf(Date.parse("2026-10-17T02:59:00-04:00")), "2026-10-16");
  assert.equal(serviceDayOf(Date.parse("2026-10-17T03:00:00-04:00")), "2026-10-17");
  assert.equal(serviceDayOf(Date.parse("2026-12-31T23:30:00-05:00")), "2026-12-31");
});

test("the closures are asked again at midnight, when a line running on the new date opens, and at 3 am", () => {
  const sunday = closuresDayOf(Date.parse("2026-10-18T23:59:00-04:00"));
  const night = closuresDayOf(Date.parse("2026-10-19T00:00:00-04:00"));
  const monday = closuresDayOf(Date.parse("2026-10-19T03:00:00-04:00"));
  assert.equal(new Set([sunday, night, monday]).size, 3);
  assert.equal(night, closuresDayOf(Date.parse("2026-10-19T02:59:00-04:00")));
});

test("the closures are asked for; a server without timetables, or no answer, greys nothing and is asked again", async () => {
  const body = { service_day: "2026-10-17", stations: [closed("Odenton", "MARC", ODENTON.point, "no MARC weekend service")] };
  const ok = async () => new Response(JSON.stringify(body), { status: 200 });
  assert.equal((await requestClosures({ fetchImpl: ok })).length, 1);
  const down = async () => new Response(JSON.stringify({ error: "x", code: "transit_unavailable" }), { status: 503 });
  assert.equal(await requestClosures({ fetchImpl: down }), null);
  const broken = async () => new Response(JSON.stringify({ stations: [{ name: 1 }] }), { status: 200 });
  assert.equal(await requestClosures({ fetchImpl: broken }), null);
  const offline = async () => {
    throw new Error("offline");
  };
  assert.equal(await requestClosures({ fetchImpl: offline }), null);
  // App sets the day it has asked for only on an answer, so a failure is retried at the next check.
  assert.match(src("App.tsx"), /if \(stations === null\) return;\s*day = today;/);
});
