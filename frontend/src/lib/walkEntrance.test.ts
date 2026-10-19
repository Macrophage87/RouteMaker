/** A Metro station on foot: its nearest entrance, not the elevator a bike needs (Stephen 2026-10-19). */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { entranceNote, stationEntrance, stationPlaceLabel, walkEntrance, type Station } from "./railStations.ts";
import { metroPlaces } from "./nearest.ts";
import { endsOnFoot } from "./presets.ts";

const station: Station = {
  id: "s",
  name: "Bethesda",
  point: [-77.0942, 38.9843],
  metro: ["red"],
  penn: false,
  elevators: [[-77.0944, 38.9846]],
  osmElevators: [],
  // Stairs and escalators: one north, one south of the station.
  entrances: [
    [-77.0942, 38.9852],
    [-77.0942, 38.9836],
  ],
};

test("on foot, the way in nearest where the rider comes from, of any kind", () => {
  assert.deepEqual(walkEntrance(station, [-77.0942, 38.99]), { point: [-77.0942, 38.9852], kind: "walk" });
  assert.deepEqual(walkEntrance(station, [-77.0942, 38.97]), { point: [-77.0942, 38.9836], kind: "walk" });
  // From nowhere yet: the one nearest the station itself, here its elevator.
  assert.deepEqual(walkEntrance(station).point, [-77.0944, 38.9846]);
  // None listed: the station itself.
  assert.deepEqual(walkEntrance({ ...station, elevators: [], entrances: [] }), { point: station.point, kind: "station" });
});

test("with a bike, still the elevator", () => {
  assert.deepEqual(stationEntrance(station, false, [-77.0942, 38.99]), { point: [-77.0944, 38.9846], kind: "elevator" });
  assert.equal(stationEntrance(station, true, [-77.0942, 38.99]).kind, "walk");
});

test("the card and the point say it in words", () => {
  assert.equal(entranceNote("walk"), "On foot, routes use its nearest entrance.");
  assert.equal(stationPlaceLabel(station, "walk"), "Bethesda Metro station, at its nearest entrance");
});

test("on foot means the Bikeshare ride types, no bike of your own at the ends", () => {
  assert.ok(endsOnFoot("bikeshare"));
  assert.ok(endsOnFoot("bikeshare-transit"));
  assert.ok(!endsOnFoot("default"));
  assert.ok(!endsOnFoot("bike-transit"));
});

test("Nearest's Metro list on foot points at the entrance nearest the search's origin", () => {
  const from: [number, number] = [-77.0942, 38.97];
  assert.deepEqual(metroPlaces([station], undefined, true, from)[0].point, [-77.0942, 38.9836]);
  assert.deepEqual(metroPlaces([station])[0].point, [-77.0944, 38.9846]);
  assert.match(metroPlaces([station], undefined, true, from)[0].details.join(" "), /On foot, routes use its nearest entrance\./);
});

test("App wires the ride type to the map card, the Nearest search and the place search", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /stationOnFoot=\{endsOnFoot\(preset\)\}/);
  assert.match(app, /onFoot: \(\) => endsOnFoot\(ride\.preset\)/);
  assert.doesNotMatch(app, /placeFromSearch\([^;]*stationEntranceForPlace\)/);
  // A start walks out toward the next point; an end or a stop is reached from the start (or Go's location).
  assert.match(app, /role === "start"\s*\? \(pointsRef\.current\[1\] \?\? goPending\.current\?\.dest \?\? null\)\s*: \(pointsRef\.current\[0\]/);
  assert.match(app, /entrance: \(place\) => entranceForPlace\(place, choice\)/);
  assert.match(app, /const goStartPick[\s\S]{0,400}entranceForPlace\(place, "start"\)/);
  const rail = readFileSync(new URL("../railInteraction.ts", import.meta.url), "utf8");
  assert.match(rail, /const \{ point, place \} = pointFor\(role\);/);
});

test("a new ride type moves a station's point to its way in for that ride, and leaves other points", async () => {
  const { stationMoves } = await import("./railStations.ts");
  const elevator: [number, number] = [-77.0944, 38.9846];
  const away: [number, number] = [-77.0942, 38.97];
  // Own bike, to Bethesda's elevator from the south; then Bikeshare: the south entrance.
  const toFoot = stationMoves([away, elevator], [station], true);
  assert.deepEqual(toFoot.map((m) => [m.index, m.to, m.kind]), [[1, [-77.0942, 38.9836], "walk"]]);
  // A new pair, not the station data's own (marks on it stay the point's).
  assert.notEqual(toFoot[0].to, station.entrances[1]);
  // And back with a bike: the elevator again.
  assert.deepEqual(stationMoves([away, [-77.0942, 38.9836]], [station], false).map((m) => m.to), [elevator]);
  // A start at the station walks out toward the next point.
  assert.deepEqual(stationMoves([elevator, [-77.0942, 38.99]], [station], true)[0].to, [-77.0942, 38.9852]);
  // Nothing at a station, or already at the right way in: nothing moves.
  assert.deepEqual(stationMoves([away, [-77.03, 38.9]], [station], true), []);
  assert.deepEqual(stationMoves([away, elevator], [station], false), []);
});

test("a moved point keeps its kind: a via stays a via, a drawn leg stays drawn", async () => {
  const { stationMoves } = await import("./railStations.ts");
  const { ViaMarks } = await import("./pointKinds.ts");
  const marks = new ViaMarks();
  const via = marks.drawn(marks.via([-77.0944, 38.9846]));
  const move = stationMoves([[-77.0942, 38.97], via, [-77.0942, 38.95]], [station], true)[0];
  const moved = marks.moved(via, move.to);
  assert.ok(marks.isVia(moved) && marks.isDrawn(moved));
});

test("App moves them in the same edit as the ride type, with the station's name, and says so", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const choose = app.slice(app.indexOf("const choosePreset = "), app.indexOf("const chooseStation = "));
  assert.match(choose, /stationMoves\(current, RAIL_STATIONS, onFoot\)/);
  assert.match(choose, /moved\[move\.index\] = VIA_MARKS\.moved\(current\[move\.index\], move\.to\)/);
  assert.match(choose, /namer\.remember\(move\.to, stationPlaceName\(move\.station\), stationPlaceLabel\(move\.station, move\.kind\)\)/);
  assert.match(choose, /commit\(moved, \{ \.\.\.rideRef\.current, preset: id, dials: next \}\);\s*announce\(said\.join\(" "\)\)/);
});
