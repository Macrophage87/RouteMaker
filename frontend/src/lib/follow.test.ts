import { test } from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import { FOLLOW_MAX_POINTS, routeRequestBody } from "./api.ts";
import { followLine } from "./gpxMatch.ts";
import { againstTrafficNotice, fidelityNotice, FOLLOW_EXACT_SAID } from "./gpxText.ts";
import { encodePolyline6 } from "./polyline.ts";

const LINE: LonLat[] = [
  [-77.0365, 38.8977],
  [-77.03, 38.9],
  [-76.61, 39.29],
];

test("a line encodes as the API's precision-6 polyline (core.dedodge.encode_polyline6 gives the same text)", () => {
  assert.equal(encodePolyline6(LINE), "gaceiAf|||qCwnCguK_vxV_isX");
  assert.equal(encodePolyline6([]), "");
});

test("an opened file not edited since follows its line; edited, or with no line, it does not", () => {
  const points: LonLat[] = [LINE[0], LINE[2]];
  const opened = { imported: { reference: LINE }, points };
  assert.deepEqual(followLine(opened, [[...LINE[0]], [...LINE[2]]]), LINE);
  assert.equal(followLine(opened, [LINE[0], LINE[1]]), undefined);
  assert.equal(followLine(opened, [LINE[0], LINE[1], LINE[2]]), undefined);
  assert.equal(followLine(null, points), undefined);
  assert.equal(followLine({ imported: { reference: [] }, points }, points), undefined);
  // Not with a loop asked for, nor once the API said it could not follow it, nor a line over 124 mi.
  assert.equal(followLine(opened, points, true), undefined);
  assert.equal(followLine({ ...opened, unfollowed: true }, points), undefined);
  const far: LonLat[] = [[-77.9, 38.1], [-76.1, 39.9]];
  assert.equal(followLine({ imported: { reference: far }, points: far }, far), undefined);
});

test("a snapped file follows the snapped line, at most FOLLOW_MAX_POINTS points of it, its ends kept", () => {
  const snapped: LonLat[] = Array.from({ length: FOLLOW_MAX_POINTS + 7 }, (_, i) => [-77 + i * 1e-5, 38.9]);
  const points: LonLat[] = [snapped[0], snapped.at(-1)!];
  const line = followLine({ imported: { reference: LINE, matched: { line: snapped, share: 1 } }, points }, points)!;
  assert.equal(line.length, FOLLOW_MAX_POINTS);
  assert.deepEqual(line[0], snapped[0]);
  assert.deepEqual(line.at(-1), snapped.at(-1));
});

test("the route request carries the line to follow, encoded, but never on a two-point ride type", () => {
  const body = JSON.parse(routeRequestBody([LINE[0], LINE[2]], "mass-ride", { follow: LINE }));
  assert.equal(body.follow, encodePolyline6(LINE));
  assert.equal(JSON.parse(routeRequestBody([LINE[0], LINE[2]], "bikeshare", { follow: LINE })).follow, undefined);
  assert.equal(JSON.parse(routeRequestBody([LINE[0], LINE[2]], "default", {})).follow, undefined);
  // The manual mode goes with the line only.
  assert.equal(body.follow_exact, undefined);
  assert.equal(JSON.parse(routeRequestBody([LINE[0], LINE[2]], "mass-ride", { follow: LINE, followExact: true })).follow_exact, true);
  assert.equal(JSON.parse(routeRequestBody([LINE[0], LINE[2]], "mass-ride", { followExact: true })).follow_exact, undefined);
});

test("a followed route says the ride type it is rated for, and where it parts from the file", () => {
  const close = fidelityNotice({ trackCovered: 0.99, routeOnTrack: 0.98, lengthRatio: 1 }, "mass-ride");
  assert.deepEqual(close, { warn: false, text: "The route follows the file's track, rated for Mass Ride." });
  const parted = fidelityNotice({ trackCovered: 0.8, routeOnTrack: 0.9, lengthRatio: 1 }, "mass-ride");
  assert.equal(parted.warn, true);
  assert.match(parted.text, /^The route follows 80% of the file's track to within .*, rated for Mass Ride; where .* no way there for Mass Ride, or bikes may not ride it\.$/);
  const exactly = fidelityNotice({ trackCovered: 0.8, routeOnTrack: 0.9, lengthRatio: 1 }, "mass-ride", true);
  assert.match(exactly.text, /no way there for Mass Ride\.$/);
  // A planned route (no ride type given) says what it said before.
  assert.equal(fidelityNotice({ trackCovered: 0.99, routeOnTrack: 0.98, lengthRatio: 1 }).text.startsWith("The route follows 99%"), true);
});

test("where a followed file rides against one-way traffic it is said, by street", () => {
  assert.equal(againstTrafficNotice(null), null);
  assert.equal(againstTrafficNotice([]), null);
  assert.match(againstTrafficNotice([{ name: "R St NW", distance_m: 400 }])!, /^The file rides against one-way traffic on R St NW \(0\.2 mi .*\)\. The route follows it there/);
  // By default the route goes round it.
  assert.match(againstTrafficNotice([{ name: "R St NW", distance_m: 400 }], false)!, /R St NW \(.*\)\. The route goes round it there\.$/);
  const many = againstTrafficNotice([
    { name: "A St", distance_m: 100 },
    { name: null, distance_m: 100 },
    { name: "C St", distance_m: 100 },
    { name: "D St", distance_m: 100 },
  ])!;
  assert.match(many, /on A St \(.*\), an unnamed street \(.*\), C St \(.*\) and 1 more\./);
});

test("App sends an opened file's line with every plan of it, and the panel stops fitting a followed route", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const follow = followLine\(importBase\.current, plan\.points, plan\.dials\.loop\);/);
  // A file the API could not follow is planned through its points from then on.
  assert.match(app, /if \(follow && result\.ok && !result\.route\.follows_file && importBase\.current\) importBase\.current\.unfollowed = true;/);
  const panel = readFileSync(new URL("../GpxPanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /if \(route\.follows_file\) \{\s*setFit\(null\);\s*return;\s*\}/);
  // The snap action is not offered beside a route that already follows the file's line.
  assert.match(panel, /!imported\.matched && !route\?\.follows_file;/);
});

test("Plan offers the manual mode while the opened file is not edited, and each change plans it again", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const followExact = follow !== undefined && importBase\.current\?\.exact === true && modeRef\.current === "plan";/);
  assert.match(app, /if \(result\.ok \|\| result\.error\.kind !== "network" \|\| followExact\) return result;/);
  assert.match(app, /importBase\.current && !importEdited \? \{ exact: importBase\.current\.exact === true, onExact: setFollowExact \}/);
  assert.match(app, /importBase\.current = \{ \.\.\.importBase\.current, exact: on, unfollowed: false \};\s*setRouteAsk/);
  const panel = readFileSync(new URL("../GpxPanel.tsx", import.meta.url), "utf8");
  // Only where the route parts from the file, or once it is on: a file followed cleanly shows nothing more.
  assert.match(panel, /\{snap\?\.onExact && imported && imported\.reference\.length >= 2 && \(snap\.exact \|\| match\?\.warn \|\| \(route\?\.against_traffic\?\.length \?\? 0\) > 0\) && \(/);
  assert.match(FOLLOW_EXACT_SAID, /^Follow the file exactly/);
});
