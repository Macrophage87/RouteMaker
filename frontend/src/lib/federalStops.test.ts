// The routing half of the federal-land item (PLAN.md FOLLOWUP-FEDERAL-LAYER, owner item 239):
// Mass Ride stops on federal land and the NPS parkway stretches, in the map, the stop list,
// the description and the road panel.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parseFederalLand, type FederalData } from "./federalLand.ts";
import {
  FEDERAL_ADVICE,
  FEDERAL_DESCRIPTION_HEADING,
  FEDERAL_ROAD_WARNING,
  FEDERAL_STOP_WARNING,
  PARKWAYS,
  areaWords,
  federalAreaAt,
  federalLines,
  federalNotes,
  parkwayByName,
  parkwayRuns,
  parkwayWarning,
  pointAlong,
  pointAreas,
  stopWarning,
  stopWarningShort,
} from "./federalStops.ts";
import { descriptionText, gpxDescriptionText } from "./routeDescription.ts";
import { PointsList } from "./pointsList.ts";
import { markerDeps } from "./mapGlue.ts";
import { formatMileRange } from "./format.ts";
import { FEDERAL_BADGE, FEDERAL_HELP } from "./federalLegend.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const square = (x: number, y: number, size: number) => [
  [x, y],
  [x + size, y],
  [x + size, y + size],
  [x, y + size],
  [x, y],
];

// Small degrees near the equator, so a step of 0.001 degrees is about 111 m.
const AREAS: FederalData = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", properties: { kind: "reservation", name: "Big Reservation", agency: "National Park Service (most U.S. Reservations)" }, geometry: { type: "Polygon", coordinates: [square(0, 0, 0.01)] } },
    { type: "Feature", properties: { kind: "capitol", name: "Capitol Grounds", agency: "Architect of the Capitol" }, geometry: { type: "Polygon", coordinates: [square(0.001, 0.001, 0.002)] } },
    { type: "Feature", properties: { kind: "military", name: "Fort Somewhere" }, geometry: { type: "Polygon", coordinates: [square(0.02, 0.02, 0.002)] } },
    { type: "Feature", properties: { kind: "nps", name: "Suitland Parkway", agency: "National Park Service" }, geometry: { type: "Polygon", coordinates: [square(0.05, -0.001, 0.02)] } },
  ],
};

const entry = (from_m: number, to_m: number, street: string | null, extra: Partial<DescriptionEntry> = {}): DescriptionEntry => ({
  kind: "stretch",
  from_m,
  to_m,
  from_mi: from_m / 1609.344,
  to_mi: to_m / 1609.344,
  street,
  tier: 2,
  facility: null,
  turn: null,
  text: `${street ?? "Unnamed"}.`,
  ...extra,
});

/** A straight route east along the equator from 0.04 to 0.08 degrees: the middle 0.05-0.07 is in the parkway's polygon. */
const LINE: LonLat[] = [
  [0.04, 0],
  [0.08, 0],
];
const LINE_M = 0.04 * 111_195;

test("a point's area is the most specific one it is in, with its agency; none outside, none before the data", () => {
  assert.deepEqual(federalAreaAt([0.002, 0.002], AREAS), { name: "Capitol Grounds", kind: "capitol", agency: "Architect of the Capitol" });
  assert.deepEqual(federalAreaAt([0.008, 0.008], AREAS), { name: "Big Reservation", kind: "reservation", agency: "National Park Service (most U.S. Reservations)" });
  assert.deepEqual(federalAreaAt([0.021, 0.021], AREAS), { name: "Fort Somewhere", kind: "military", agency: null });
  assert.equal(federalAreaAt([0.5, 0.5], AREAS), null);
  assert.equal(federalAreaAt([0.002, 0.002], null), null);
});

test("the stop warning is the owner's words, naming the area and its manager where known", () => {
  const capitol = federalAreaAt([0.002, 0.002], AREAS)!;
  assert.equal(FEDERAL_STOP_WARNING, "federal land: check permit requirements for gathering here");
  assert.equal(areaWords(capitol), "Capitol Grounds, managed by Architect of the Capitol");
  assert.equal(stopWarning("End", capitol), "End is inside Capitol Grounds, managed by Architect of the Capitol – federal land: check permit requirements for gathering here.");
  assert.equal(stopWarningShort(capitol), "Inside Capitol Grounds, managed by Architect of the Capitol – federal land: check permit requirements for gathering here.");
  // No agency in the data (Military Bases): the kind, never an invented manager.
  assert.equal(areaWords(federalAreaAt([0.021, 0.021], AREAS)!), "Fort Somewhere (Military installation)");
});

test("each point's area for the rows and markers, on a Mass Ride with the data only", () => {
  const points: LonLat[] = [[0.002, 0.002], [0.5, 0.5], [0.021, 0.021]];
  assert.deepEqual(
    pointAreas(points, AREAS, true).map((a) => a?.name ?? null),
    ["Capitol Grounds", null, "Fort Somewhere"],
  );
  assert.deepEqual(pointAreas(points, AREAS, false), [], "another ride type");
  assert.deepEqual(pointAreas(points, null, true), [], "before the data");
});

test("the five parkways are told by their OpenStreetMap names, and nothing else is", () => {
  const named: Array<[string, string]> = [
    ["Rock Creek and Potomac Parkway Northwest", "Rock Creek and Potomac Pkwy"],
    ["Rock Creek & Potomac Pkwy", "Rock Creek and Potomac Pkwy"],
    ["Rock Creek Parkway", "Rock Creek and Potomac Pkwy"],
    ["George Washington Memorial Parkway", "George Washington Memorial Pkwy"],
    ["Clara Barton Parkway", "Clara Barton Pkwy"],
    ["Suitland Parkway Southeast", "Suitland Pkwy"],
    ["Baltimore-Washington Parkway", "Baltimore-Washington Pkwy"],
  ];
  for (const [street, name] of named) assert.equal(parkwayByName(street)?.name, name, street);
  for (const street of ["Rock Creek Park & Piney Branch Parkway", "Beach Drive Northwest", "Oxon Run Parkway", "Constitution Avenue Northwest", "Potomac Avenue", null, ""]) {
    assert.equal(parkwayByName(street), null, String(street));
  }
  assert.equal(PARKWAYS.length, 5);
});

test("parkway runs: by name, joined across a short gap, and in route order", () => {
  const route = { geometry: { type: "LineString" as const, coordinates: LINE }, distance_m: LINE_M };
  const runs = parkwayRuns(
    [
      entry(0, 400, "Constitution Avenue Northwest"),
      entry(400, 900, "Rock Creek and Potomac Parkway Northwest"),
      { ...entry(900, 900, null), kind: "junction" },
      entry(950, 1600, "Rock Creek and Potomac Parkway Northwest", { tier: 3 }),
      entry(1600, 2000, "Virginia Avenue Northwest"),
      entry(2000, 2400, "Rock Creek and Potomac Parkway Northwest"),
    ],
    route,
    null,
  );
  assert.deepEqual(
    runs.map((r) => [r.parkway.name, r.from_m, r.to_m]),
    [
      ["Rock Creek and Potomac Pkwy", 400, 1600],
      ["Rock Creek and Potomac Pkwy", 2000, 2400],
    ],
  );
});

test("parkway runs by the NPS layer: an unnamed road in its polygon is, a path or a city street there is not (239 (c))", () => {
  const route = { geometry: { type: "LineString" as const, coordinates: LINE }, distance_m: LINE_M };
  // 0.05 to 0.07 degrees is about 1,112 to 3,336 m along.
  const inside = [1300, 3100] as const;
  assert.deepEqual(
    parkwayRuns([entry(...inside, null)], route, AREAS).map((r) => r.parkway.name),
    ["Suitland Pkwy"],
  );
  assert.deepEqual(parkwayRuns([entry(...inside, "Suitland Pkwy SE ramp")], route, AREAS).map((r) => r.parkway.name), ["Suitland Pkwy"]);
  assert.deepEqual(parkwayRuns([entry(...inside, null, { facility: "path" })], route, AREAS), [], "the trail beside it");
  assert.deepEqual(parkwayRuns([entry(...inside, "Firth Sterling Avenue Southeast")], route, AREAS), [], "a city street through it");
  assert.deepEqual(parkwayRuns([entry(0, 900, null)], route, AREAS), [], "outside the polygon");
  assert.deepEqual(parkwayRuns([entry(...inside, null)], route, null), [], "no data: names only");
});

test("a point along the line, for the stretch's quarter points", () => {
  assert.deepEqual(pointAlong(LINE, 0), [0.04, 0]);
  const middle = pointAlong(LINE, LINE_M / 2)!;
  assert.ok(Math.abs(middle[0] - 0.06) < 1e-6 && middle[1] === 0, String(middle));
  assert.deepEqual(pointAlong(LINE, LINE_M * 2), [0.08, 0], "past the end: the end");
  assert.equal(pointAlong([], 10), null);
});

test("the parkway warning: miles first with kilometres in brackets, named and called a federal road", () => {
  const [run] = parkwayRuns([entry(3380, 5520, "Clara Barton Parkway")], { geometry: { type: "LineString", coordinates: LINE }, distance_m: LINE_M }, null);
  assert.equal(formatMileRange(3380, 5520), "2.1 to 3.4 mi (3.4 to 5.5 km)");
  assert.equal(
    parkwayWarning(run),
    "2.1 to 3.4 mi (3.4 to 5.5 km): Clara Barton Pkwy, a National Park Service parkway – federal road: check permit requirements for riding it as a group.",
  );
  assert.match(FEDERAL_ROAD_WARNING, /^federal road: /);
});

const massRoute = (description: DescriptionEntry[]): RouteResponse =>
  ({
    preset: "mass-ride",
    geometry: { type: "LineString", coordinates: LINE },
    distance_m: LINE_M,
    description,
    description_overview: null,
  }) as unknown as RouteResponse;

test("a Mass Ride's notes: the stops on federal land by name, then the parkway runs; nothing on another ride type", () => {
  const route = massRoute([entry(0, 1000, "Constitution Avenue Northwest"), entry(1300, 3100, null)]);
  const points: LonLat[] = [[0.002, 0.002], [0.5, 0.5], [0.021, 0.021], [0.008, 0.008]];
  const notes = federalNotes(route, points, AREAS);
  assert.deepEqual(notes.stops, [
    "Start is inside Capitol Grounds, managed by Architect of the Capitol – federal land: check permit requirements for gathering here.",
    "Stop 2 is inside Fort Somewhere (Military installation) – federal land: check permit requirements for gathering here.",
    "End is inside Big Reservation, managed by National Park Service (most U.S. Reservations) – federal land: check permit requirements for gathering here.",
  ]);
  assert.equal(notes.parkways.length, 1);
  assert.match(notes.parkways[0], /: Suitland Pkwy, a National Park Service parkway – federal road/);
  assert.deepEqual(federalLines(notes), [FEDERAL_DESCRIPTION_HEADING, ...notes.stops, ...notes.parkways]);
  assert.deepEqual(federalNotes({ ...route, preset: "default" } as RouteResponse, points, AREAS), { stops: [], parkways: [] });
  assert.deepEqual(federalNotes(route, points, null), { stops: [], parkways: [] });
  // Nothing to say: no lines, not a heading over an empty list.
  assert.deepEqual(federalLines(federalNotes(massRoute([entry(0, 1000, "K Street")]), [[0.5, 0.5]], AREAS)), []);
  assert.deepEqual(federalLines(null), []);
});

test("the heading line says it is information and that ownership is not police jurisdiction (239)", () => {
  assert.match(FEDERAL_DESCRIPTION_HEADING, /^Federal land on this route\. /);
  assert.match(FEDERAL_ADVICE, /not legal advice/);
  assert.match(FEDERAL_ADVICE, /ownership is not police jurisdiction/);
});

test("the description text and the GPX description carry the lines before the steps", () => {
  const route = massRoute([entry(0, 1000, "Constitution Avenue Northwest")]);
  const lines = [FEDERAL_DESCRIPTION_HEADING, "Start is inside X – federal land: check permit requirements for gathering here."];
  const text = descriptionText(route, "full", lines).split("\n");
  assert.equal(text[1], FEDERAL_DESCRIPTION_HEADING);
  assert.equal(text[2], lines[1]);
  assert.match(text[3], /^1\. /);
  const gpx = gpxDescriptionText(route, lines).split("\n");
  assert.deepEqual(gpx.slice(1, 3), lines);
  assert.match(gpx[3], /^1\. /);
  // Without lines, as before.
  assert.doesNotMatch(descriptionText(route, "full"), /Federal land/);
});

test("the stop list: a row on federal land carries its warning before Remove, and only that row", () => {
  const rows = [
    { role: "Start", place: undefined, coords: "38.8995, -77.0365" },
    { role: "End", place: undefined, coords: "38.9100, -77.0400" },
  ];
  const warning = "Inside Lafayette Square, managed by National Park Service – federal land: check permit requirements for gathering here.";
  const html = renderToStaticMarkup(createElement(PointsList, { rows, warnings: [warning, null], onRemove: () => {}, removeRef: () => {} }));
  assert.match(html, /<li class="point-on-federal"><span class="point-name">Start<\/span><span class="coords">[^<]+<\/span><span class="point-federal">Inside Lafayette Square, managed by National Park Service – federal land: check permit requirements for gathering here\.<\/span><button/);
  assert.match(html, /<li><span class="point-name">End<\/span><span class="coords">[^<]+<\/span><button/);
  const plain = renderToStaticMarkup(createElement(PointsList, { rows, onRemove: () => {}, removeRef: () => {} }));
  assert.doesNotMatch(plain, /point-federal|point-on-federal/);
});

test("the markers follow the warnings: the same words keep them, new words rebuild them", () => {
  const changed = (a: readonly unknown[], b: readonly unknown[]) => a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]));
  const points: LonLat[] = [[-77, 38.9]];
  assert.equal(changed(markerDeps(points, 0, false, ["x", null]), markerDeps(points, 0, false, ["x", null])), false);
  assert.equal(changed(markerDeps(points, 0, false, [null]), markerDeps(points, 0, false, ["x"])), true);
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 0, false, [])), false);
});

test("the map's markers say the warning in their name and title and wear the badge", () => {
  const map = source("../MapView.tsx");
  assert.match(map, /const warning = props\.pointWarnings\?\.\[index\] \?\? null;/);
  assert.match(map, /element\.className = `pin pin-\$\{kind\}\$\{warning \? " pin-federal" : ""\}`;/);
  assert.match(map, /const named = warning \? `\$\{name\}\. \$\{warning\}` : name;/);
  assert.match(map, /element\.setAttribute\("aria-label", via \? `\$\{said\} Drag to move; click for Remove\.` : `\$\{said\} Drag to move\.`\);/);
  const css = source("../styles.css");
  assert.match(css, /\.pin-federal::before \{\s+content: "!";/);
  assert.match(css, /\.point-federal::before \{\s+content: "!";/);
});

test("the road panel names the federal area at the spot, on a Mass Ride (the keyboard's way, I at the map's center)", () => {
  const app = source("../App.tsx");
  assert.match(app, /federal=\{roadInfo && federalShown\(preset, true\) \? federalAreaAt\(roadInfo\.point, federalData\) : null\}/);
  const dialog = source("../RoadInfoDialog.tsx");
  assert.match(dialog, /const federalSaid = federal \? stopWarningShort\(federal\) : "";/);
  assert.match(dialog, /setSaid\(\[infoSaid\(next\), federalSaidRef\.current\]\.filter\(Boolean\)\.join\(" "\)\);/);
  assert.match(dialog, /<span className="road-info-label">Federal land:<\/span> \{federalSaid\}\{" "\}\s*<span className="road-info-federal-note">\{FEDERAL_ADVICE\}<\/span>/);
});

test("the description component lists the lines under their heading, and copies and downloads them", () => {
  const component = source("../RouteDescription.tsx");
  assert.match(component, /<p className="federal-route-heading" id=\{`\$\{listId\}-federal`\}>/);
  assert.match(component, /<ul aria-labelledby=\{`\$\{listId\}-federal`\}>/);
  assert.equal((component.match(/\{federalBlock\(/g) ?? []).length, 2, "in the fold and the old section");
  const app = source("../App.tsx");
  assert.match(app, /federalLines\(federalNotes\(shown, routedPoints, federalData\)\)/);
  assert.match(app, /<GpxPanel[\s\S]*?federal=\{federalRoute\}/);
});

test("the help names the badge, the Directions lines and the keyboard's way, and stays short", () => {
  assert.match(FEDERAL_BADGE, /! badge/);
  assert.match(FEDERAL_BADGE, /Directions names those stops/);
  assert.match(FEDERAL_HELP, /Press I on the map/);
  for (const text of [FEDERAL_BADGE, FEDERAL_HELP]) assert.ok(text.split(" ").length <= 40, text);
});

// The real file: places a Mass Ride uses.
const REAL = parseFederalLand(JSON.parse(source("../federal-data/federal-land.json")))!;

test("the real data: Lafayette Square and the Capitol grounds, and nothing on an ordinary block", () => {
  assert.deepEqual(federalAreaAt([-77.0365, 38.8995], REAL), { name: "Lafayette Square", kind: "nps", agency: "National Park Service" });
  assert.equal(federalAreaAt([-77.009, 38.8899], REAL)?.agency, "Architect of the Capitol");
  assert.equal(federalAreaAt([-77.04, 38.91], REAL), null);
});

test("the real data: an unnamed road in the Rock Creek and Potomac Parkway's polygon is on the parkway", () => {
  const line: LonLat[] = [
    [-77.0555, 38.9045],
    [-77.0555, 38.9055],
  ];
  const length = 111.2;
  const runs = parkwayRuns([entry(0, length, null)], { geometry: { type: "LineString", coordinates: line }, distance_m: length }, REAL);
  assert.deepEqual(runs.map((r) => r.parkway.name), ["Rock Creek and Potomac Pkwy"]);
});

test("the words never characterise a neighbourhood", () => {
  const all = [FEDERAL_STOP_WARNING, FEDERAL_ROAD_WARNING, FEDERAL_ADVICE, FEDERAL_DESCRIPTION_HEADING, FEDERAL_BADGE].join(" ");
  assert.doesNotMatch(all, /neighbou?rhood|dangerous|unsafe|crime/i);
});
