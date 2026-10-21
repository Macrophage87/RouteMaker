import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { ClosedStation, StationAlert } from "./api.ts";
import { MATCH_M, RAIL_STATUS_MS, closedLabel, closedReason, matchAlerts, matchClosures, requestClosures, withMetroClosed } from "./railClosures.ts";
import { ALERT_BADGE_ICON, ELEVATOR_OUT_ICON, railFeatures, closedIconId, type Station } from "./railStations.ts";
import { railHitFrom, railImages, railLayers, RAIL_LAYERS } from "./railLayer.ts";
import { ALERT_FILL, CLOSED_STRIKE, OUT_STRIKE, alertBadgeIcon, closedStationIcon, elevatorOutIcon, hexToRgb } from "./stationIcons.ts";
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
  const names = railLayers().find((layer) => layer.id === RAIL_LAYERS.names) as { paint: Record<string, unknown> };
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

test("the closures are asked for; a server without timetables, or no answer, greys nothing and is asked again", async () => {
  const body = { service_day: "2026-10-17", stations: [closed("Odenton", "MARC", ODENTON.point, "no MARC weekend service")] };
  const ok = async () => new Response(JSON.stringify(body), { status: 200 });
  assert.deepEqual(await requestClosures({ fetchImpl: ok }), { stations: body.stations, alerts: [] });
  const withAlerts = { ...body, alerts: [alertAt(EASTERN.point, true, false), { name: "x" }] };
  const okAlerts = async () => new Response(JSON.stringify(withAlerts), { status: 200 });
  // A malformed badge is left out, not the answer.
  assert.deepEqual((await requestClosures({ fetchImpl: okAlerts }))?.alerts, [alertAt(EASTERN.point, true, false)]);
  const down = async () => new Response(JSON.stringify({ error: "x", code: "transit_unavailable" }), { status: 503 });
  assert.equal(await requestClosures({ fetchImpl: down }), null);
  const broken = async () => new Response(JSON.stringify({ stations: [{ name: 1 }] }), { status: 200 });
  assert.equal(await requestClosures({ fetchImpl: broken }), null);
  const offline = async () => {
    throw new Error("offline");
  };
  assert.equal(await requestClosures({ fetchImpl: offline }), null);
  // App counts only an answer as asked, so a failure is retried at the next check; asked again every
  // few minutes while in view (WMATA's closures and badges change within the day) and when back in view.
  const app = src("App.tsx");
  assert.match(app, /if \(status === null\) return;\s*askedAt = Date\.now\(\);/);
  assert.match(app, /document\.visibilityState === "hidden"/);
  assert.match(app, /addEventListener\("visibilitychange", check\)/);
  assert.equal(RAIL_STATUS_MS, 5 * 60_000);
});

// --- WMATA's badges (the owner, 2026-10-18: "Put a little notice marker on all the stations that have
// alerts", "For elevator out, use an X'd out elevator icon") ---------------------------------------

const alertAt = (point: [number, number], alert: boolean, elevatorOut: boolean): StationAlert => ({
  name: "x",
  lon: point[0],
  lat: point[1],
  alert,
  elevator_out: elevatorOut,
});

test("a badge goes to the nearest Metro station within reach; two for one station are merged", () => {
  const badges = matchAlerts(STATIONS, [
    alertAt(EASTERN.point, true, false),
    alertAt([EASTERN.point[0] + 0.001, EASTERN.point[1]], false, true),
    // Odenton has no Metro lines; a point nowhere near a station matches nothing.
    alertAt(ODENTON.point, true, true),
    alertAt([-77.5, 38.5], true, true),
  ]);
  assert.deepEqual([...badges], [["eastern", { alert: true, elevatorOut: true }]]);
});

test("on the map: the alert up and right, the elevator out up and left; none on a closed or MARC-only station", () => {
  const badges = (s: Station) => (s.id === "eastern" || s.id === "union" ? { alert: true, elevatorOut: true } : null);
  const shown = (visibility: { metro: boolean; marc: boolean }, isClosed: (s: Station) => boolean = () => false) =>
    railFeatures(STATIONS, visibility, isClosed, badges).features.filter((f) => f.properties.kind === "badge").map((f) => f.properties);
  assert.deepEqual(
    shown(BOTH).filter((p) => p.id === "eastern"),
    [
      { kind: "badge", id: "eastern", name: "Eastern Market", icon: ALERT_BADGE_ICON, offset: [10, -10] },
      { kind: "badge", id: "eastern", name: "Eastern Market", icon: ELEVATOR_OUT_ICON, offset: [-10, -10] },
    ],
  );
  // Struck through instead.
  assert.equal(shown(BOTH, (s) => s.id === "eastern").filter((p) => p.id === "eastern").length, 0);
  // Union Station shown for MARC alone: WMATA's badges are Metro's.
  assert.equal(shown({ metro: false, marc: true }).length, 0);
  // Made at load, drawn from street level, and a tap on one opens its station's card (which says it in words).
  const ids = railImages(STATIONS, "#8a6500", 1).map((image) => image.id);
  assert.ok(ids.includes(ALERT_BADGE_ICON) && ids.includes(ELEVATOR_OUT_ICON));
  const layer = railLayers().find((l) => l.id === RAIL_LAYERS.badges) as { layout: Record<string, unknown>; minzoom: number };
  assert.deepEqual(layer.layout["icon-offset"], ["get", "offset"]);
  assert.equal(layer.minzoom, 12);
  assert.deepEqual(railHitFrom([{ properties: { kind: "badge", id: "eastern" } }]), { id: "eastern" });
  assert.match(src("railInteraction.ts"), /RAIL_LAYERS\.badges/);
  assert.match(src("MapView.tsx"), /railBadges/);
});

test("the alert badge is an amber triangle with a dark '!'; the elevator-out badge is struck through in red", () => {
  const at = (icon: { data: Uint8Array; width: number }, x: number, y: number) =>
    Array.from(icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 4));
  const alert = alertBadgeIcon(1, 13);
  assert.deepEqual(at(alert, 6, 6).slice(0, 3), hexToRgb("#1f2937")); // the "!"
  assert.deepEqual(at(alert, 4, 9).slice(0, 3), hexToRgb(ALERT_FILL));
  assert.equal(at(alert, 0, 0)[3], 0); // outside the triangle
  const out = elevatorOutIcon(1, 14);
  assert.deepEqual(at(out, 7, 7).slice(0, 3), hexToRgb(OUT_STRIKE));
  assert.deepEqual(at(out, 2, 2).slice(0, 3), hexToRgb(OUT_STRIKE));
});

test("Metro closed at a station MARC still serves: not struck through, but badged", () => {
  const closures = matchClosures(STATIONS, [closed("Union Station", "Metro", UNION.point, "WMATA service alert")]);
  assert.equal(closedReason(UNION, BOTH, closures), null);
  assert.deepEqual(withMetroClosed(null, UNION, BOTH, closures), { alert: true, elevatorOut: false });
  // Metro alone shown: struck through instead; MARC alone shown: Metro's closure is not this map's.
  assert.equal(withMetroClosed(null, UNION, { metro: true, marc: false }, closures), null);
  assert.equal(withMetroClosed(null, UNION, { metro: false, marc: true }, closures), null);
  assert.equal(withMetroClosed(null, EASTERN, BOTH, closures), null);
});
