import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DOCK_CHOICES, dockChoiceLine, dockChoices } from "./rebalanceDock.ts";
import type { NearbyStation } from "./stations.ts";

const station = (id: string, lon: number, lat: number, distance_m: number, docks = 10): NearbyStation => ({
  station_id: id,
  name: `Dock ${id}`,
  lon,
  lat,
  percent_full: 10,
  distance_m,
  bikes: 1,
  ebikes: 0,
  docks,
});

const at: [number, number] = [-77.0, 38.9];

test("the drop-offs to choose at the crowded dock: nearest first, three at most, never that dock (Stephen, 2026-11-07)", () => {
  const listed = [
    station("far", -77.02, 38.9, 1700),
    station("here", -77.0, 38.9001, 10),
    station("near", -77.005, 38.9, 430),
    station("mid", -77.01, 38.9, 870),
    station("farther", -77.03, 38.9, 2600),
  ];
  const choices = dockChoices(listed, at, "Dock pick-up");
  assert.deepEqual(choices.map((c) => c.id), ["near", "mid", "far"]);
  assert.equal(choices.length, DOCK_CHOICES);
  assert.deepEqual(choices[0]!.point, [-77.005, 38.9]);
  // The pick-up dock by name too, wherever the feed puts it.
  assert.deepEqual(dockChoices([{ ...station("same", -77.01, 38.9, 870), name: "Dock pick-up" }], at, "Dock pick-up"), []);
  assert.deepEqual(dockChoices([], at), []);
});

test("each choice says how far and how much room", () => {
  const [choice] = dockChoices([station("near", -77.005, 38.9, 430, 7)], at);
  assert.match(dockChoiceLine(choice!), /^0\.3 mi \(430 m\) away, 7 open docks$/);
});

test("the ride holds at the crowded dock, asks the drop-off list there live, and rides to the one chosen", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  // Reaching the dock asks; while asking, fixes move the marker only.
  // From the dock; a bike taken at another and the line joined along it, from there.
  assert.match(ride, /if \(rebalance && approach\) askDocksRef\.current\(haversineM\(fix\.point, approach\.at\) > DOCK_AWAY_M \? fix\.point : approach\.at\);/);
  assert.match(ride, /if \(dockingRef\.current\) \{\s*const held = /);
  assert.match(ride, /const result = await requestStations\(at, "dropoff"\);/);
  // The choice is ridden from the dock, its name the finish, the time choosing not counted.
  assert.match(ride, /const points: LonLat\[\] = \[asking\.at, choice\.point\];\s*const result = await askRoute\(points, null, false\);/);
  assert.match(ride, /statsRef\.current = statsPause\(statsRef\.current\);/);
  // The card stands in for the cue, and the chosen dock goes to the summary.
  assert.match(ride, /\{docking \? \(\s*<RebalanceDockCard /);
  // A re-plan asked while choosing is dropped; the focus goes back to the ride's heading.
  assert.match(ride, /replanTicket\.current \+= 1;\s*const dock = t\("Dock at \{place\}\.", \{ place: choice\.name \}\);/);
  assert.match(ride, /notify\(dockChosenSaid\(choice\.name\)\);\s*\/\/[^\n]*\n\s*headingRef\.current\?\.focus\(\);/);
  assert.match(ride, /statsRef\.current, dockChosen\.current \? \{ name: dockChosen\.current, route: routeRef\.current, points: plan\.current\.points \} : null\);/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /dock: docked\?\.name \?\? share\.end\.name/);
  // Keep riding carries on to the chosen dock, its plan kept for the day's figures.
  assert.match(app, /const kept = start && docked \? \{ \.\.\.start, planned: start\.planned \?\? start\.route, route: docked\.route, points: docked\.points, trip: start\.trip \? \{ \.\.\.start\.trip, approach: null, docked: docked\.name \} : null \} : start;/);
  assert.match(app, /const planRoute = start\?\.planned \?\? start\?\.route;/);
  assert.match(ride, /const rebalance = plannedRoute\.preset === "rebalance" \|\| !!plannedTrip\?\.docked;/);
  // The card: the nearest first and primary; with none, Try again and the plan's own dock.
  const card = readFileSync(new URL("../RebalanceDockCard.tsx", import.meta.url), "utf8");
  assert.match(card, /className=\{i === 0 \? "primary" : "secondary"\}/);
  assert.match(card, /\{DOCK_RETRY\}[\s\S]*dockAsPlanned\(ask\.planned\.name\)/);
});
