import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import { lightClock, solarDay } from "./lightTimes.ts";
import { HeadingTrack, aheadSaid, foodNearestPlaces, headingOf, linesOf, mapLines, onRoadSaid, roadsAhead, roamLight, roamLink, roamLinkFrom, type RoadLine, type RoamMap, type StressLine } from "./roam.ts";

// A small grid near Dupont Circle: metres to degrees, close enough at this latitude.
const O: LonLat = [-77.04, 38.91];
const M_LON = 1 / (111_320 * Math.cos((38.91 * Math.PI) / 180));
const M_LAT = 1 / 110_540;
const at = (east: number, north: number): LonLat => [O[0] + east * M_LON, O[1] + north * M_LAT];

// Main St runs north through the rider; A St crosses it 200 m ahead, B St ends on it from the east 450 m ahead,
// C St crosses 300 m behind, and D St crosses 1.5 km ahead (past the half mile looked at).
const ROADS: RoadLine[] = [
  { name: "Main St", lines: [[at(0, -600), at(0, 0), at(0, 1000)]] },
  { name: "Main St", lines: [[at(0, 1000), at(0, 1600)]] },
  { name: "A St", lines: [[at(-300, 200), at(300, 200)]] },
  { name: "B St", lines: [[at(0, 450), at(400, 450)]] },
  { name: "C St", lines: [[at(-300, -300), at(300, -300)]] },
  { name: "D St", lines: [[at(-300, 1500), at(300, 1500)]] },
];
const STRESS: StressLine[] = [
  { tier: 2, lines: [[at(0, -600), at(0, 1600)]] },
  // A St is busier west of Main than east of it: the busier is said.
  { tier: 3, lines: [[at(-300, 200), at(-1, 200)]] },
  { tier: 1, lines: [[at(1, 200), at(300, 200)]] },
  { tier: 4, half: true, lines: [[at(1, 450), at(400, 450)]] },
];

test("Roam names the road ridden and the roads ahead, nearest first, with their stress", () => {
  const found = roadsAhead(at(0, 0), 0, ROADS, STRESS);
  assert.deepEqual(found.on, { name: "Main St", tier: 2 });
  assert.deepEqual(
    found.ahead.map((r) => [r.name, Math.round(r.distanceM), r.tier]),
    [
      ["A St", 200, 3],
      // A half step reads as the level above: 4.5 is said Avoid.
      ["B St", 450, 5],
    ],
  );
});

test("Roam looks the way the rider is going: heading south, C St is ahead and A St behind", () => {
  const found = roadsAhead(at(0, 0), 180, ROADS, STRESS);
  assert.deepEqual(
    found.ahead.map((r) => r.name),
    ["C St"],
  );
});

test("standing still (no heading), only the road ridden is named", () => {
  const found = roadsAhead(at(3, 0), null, ROADS, STRESS);
  assert.equal(found.on?.name, "Main St");
  assert.deepEqual(found.ahead, []);
});

test("at a junction the road along the heading is the one ridden, not the cross street a little nearer", () => {
  const found = roadsAhead(at(4, 201), 0, ROADS, STRESS);
  assert.equal(found.on?.name, "Main St");
  const east = roadsAhead(at(4, 201), 90, ROADS, STRESS);
  assert.equal(east.on?.name, "A St");
});

test("off any named road, the roads a straight line ahead crosses", () => {
  const park = roadsAhead(at(-150, 0), 0, ROADS, STRESS);
  assert.equal(park.on, null);
  assert.deepEqual(
    park.ahead.map((r) => r.name),
    ["A St"],
  );
});

test("the words: US units first, the stress after", () => {
  assert.equal(onRoadSaid({ name: "Main St", tier: 2 }), "On Main St, LTS 2.");
  assert.equal(onRoadSaid({ name: "Main St", tier: null }), "On Main St.");
  assert.equal(onRoadSaid(null), "No named road here.");
  assert.equal(
    aheadSaid([
      { name: "A St", tier: 3, distanceM: 100 },
      { name: "B St", tier: null, distanceM: 450 },
    ]),
    "Ahead: A St in 350 feet, LTS 3; B St in 0.3 miles.",
  );
  assert.equal(aheadSaid([]), "");
});

test("the heading: the GPS's while moving, else from a fix far enough back", () => {
  assert.equal(headingOf(at(0, 0), 45, null), 45);
  assert.equal(headingOf(at(0, 20), null, at(0, 0)), 0);
  assert.equal(Math.round(headingOf(at(20, 0), null, at(0, 0)) ?? -1), 90);
  assert.equal(headingOf(at(0, 3), null, at(0, 0)), null);
  assert.equal(headingOf(at(0, 3), null, null), null);
});

test("food places search like water, named by name or kind", () => {
  const [place] = foodNearestPlaces([{ id: "n1", lon: -77, lat: 38.9, kind: "c", name: "Bean", cuisine: ["coffee_shop"], hours: "Mo-Fr 07:00-15:00" }]);
  assert.deepEqual(place.point, [-77, 38.9]);
  assert.equal(place.title, "Bean");
  assert.ok(place.details[0].includes("coffee shop"));
  assert.ok(place.details[1].startsWith("Hours as mapped"));
});

test("only lines are read from the map's features", () => {
  assert.deepEqual(linesOf({ type: "LineString", coordinates: [[0, 0], [1, 1]] }), [[[0, 0], [1, 1]]]);
  assert.equal(linesOf({ type: "MultiLineString", coordinates: [[[0, 0], [1, 1]]] }).length, 1);
  assert.deepEqual(linesOf({ type: "Point", coordinates: [0, 0] }), []);
  assert.deepEqual(linesOf(null), []);
});

test("the map's own tiles: named roads from the base map, levels from the stress tiles, only near the rider", () => {
  const asked: string[] = [];
  const map: RoamMap = {
    getSource: (id) => (id === "protomaps" || id === "stress" ? {} : undefined),
    querySourceFeatures: (id, { sourceLayer }) => {
      asked.push(`${id}/${sourceLayer}`);
      if (id === "protomaps")
        return [
          { geometry: { type: "LineString", coordinates: [at(0, -50), at(0, 50)] }, properties: { name: "Main St", "name:en": "Main Street" } },
          { geometry: { type: "LineString", coordinates: [at(-50, 20), at(50, 20)] }, properties: { kind: "minor_road" } },
          { geometry: { type: "LineString", coordinates: [at(5000, 0), at(5100, 0)] }, properties: { name: "Far Rd" } },
        ];
      return [
        { geometry: { type: "LineString", coordinates: [at(0, -50), at(0, 50)] }, properties: { tier: 2, half: true } },
        // A mountain-bike-only trail is not a road's level (drawn not for routes).
        { geometry: { type: "LineString", coordinates: [at(0, -50), at(0, 50)] }, properties: { tier: 4, mtb: true } },
      ];
    },
  };
  const { roads, stress } = mapLines(map, at(0, 0));
  assert.deepEqual(asked, ["protomaps/roads", "stress/stress"]);
  assert.deepEqual(
    roads.map((r) => r.name),
    ["Main Street"],
  );
  assert.deepEqual(
    stress.map((s) => [s.tier, s.half]),
    [[2, true]],
  );
  // No map sources yet (the map still loading): nothing, and nothing asked.
  const bare = mapLines({ getSource: () => undefined, querySourceFeatures: () => { throw new Error("asked"); } }, at(0, 0));
  assert.deepEqual(bare, { roads: [], stress: [] });
});

test("a road that ends just short of the one ridden (a T junction mapped 2 m off) is met; a path alongside is not", () => {
  const roads: RoadLine[] = [
    { name: "Main St", lines: [[at(0, -600), at(0, 1000)]] },
    // Ends 2 m east of Main St: no crossing, only the end meets it.
    { name: "E St", lines: [[at(2, 300), at(400, 300)]] },
    // A named path 2 m beside Main St, its bends all within 3 m of it, ending well past the half mile.
    { name: "Main St Trail", lines: [[at(2, -900), at(2, 100), at(2.5, 400), at(2, 1200)]] },
  ];
  const stress: StressLine[] = [{ tier: 3, lines: [[at(2, 300), at(400, 300)]] }];
  const found = roadsAhead(at(0, 0), 0, roads, stress);
  assert.deepEqual(
    found.ahead.map((r) => [r.name, Math.round(r.distanceM), r.tier]),
    [["E St", 300, 3]],
  );
});

test("the heading holds between fixes too close to take one from (a phone with no GPS heading at 5 m a second)", () => {
  const track = new HeadingTrack();
  const headings = [0, 5, 10, 15, 20, 25, 30].map((north) => track.step(at(0, north), null));
  // None until 10 m have been ridden; north from then on, every fix, never back to none.
  assert.deepEqual(headings.map((h) => (h === null ? null : Math.round(h))), [null, null, 0, 0, 0, 0, 0]);
  // Turning east: the new way once 10 m on from the last point taken.
  const east = [5, 10, 15].map((e) => track.step(at(e, 30), null));
  assert.ok(east[2] !== null && Math.round(east[2]) > 45, String(east));
  // The GPS's own heading wins while it gives one.
  assert.equal(track.step(at(20, 30), 180), 180);
});

test("App: Roam is Go's one button with no destination, a detour's end comes back to it, and the plan is shut while roaming", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /points\.length === 0 && !isMassRide\(preset\)\s*\? \{ label: ROAM_NAME, start: true, busy: false, onPress: startRoam \}/);
  assert.match(app, /if \(start\?\.roam\) \{\s*setRiding\(false\);\s*setRideStart\(null\);\s*setRideView\(null\);\s*setFollow\(true\);\s*setRoaming\(true\);\s*announce\(BACK_TO_ROAM\);\s*return;/);
  assert.match(app, /beginRide\(ridePrefs, false, \{ route: result\.route, points: asked, roam: true \}\);/);
  // A bikeshare or transit ride type rides the detour as the default ride.
  assert.match(app, /requestRoute\(asked, plain \? "default" : preset,/);
  // Nothing on the map changes the plan while roaming: the stop cards offer nothing, and the overlays are off.
  assert.match(app, /const onBike = riding \|\| roaming;/);
  assert.match(app, /if \(onBike\) return null;/);
  assert.match(app, /useEffect\(\(\) => closeStopCard\(\), \[onBike, mode\]\);/);
  assert.match(app, /onMapClick=\{onBike \|\| reviewing \? ignore : place\}/);
  assert.doesNotMatch(app, /\bon=\{[^}]*&& !riding\}/);
});

test("a Roam broadcast's link: the ride's id and the leader key in the fragment, read back; anything else is not one", () => {
  const id = "0123456789abcdef0123456789abcdef";
  const lead = "fedcba9876543210fedcba9876543210";
  const link = roamLink("https://example.org", id, lead);
  assert.equal(link, `https://example.org/#roam=${id}&lead=${lead}`);
  assert.deepEqual(roamLinkFrom(new URL(link).hash), { id, lead });
  assert.equal(roamLinkFrom(`#roam=${id}`), null);
  assert.equal(roamLinkFrom(`#roam=xyz&lead=${lead}`), null);
  assert.equal(roamLinkFrom("#p=1,2;3,4"), null);
});

test("sunrise and sunset: the next of each, in order, with the time till it within the hour", () => {
  const dc: LonLat = [-77.04, 38.91];
  // 2026-10-22 at noon in Washington (16:00 UTC): sunset comes first, then tomorrow's sunrise.
  const noon = Date.UTC(2026, 9, 22, 16, 0);
  const day = roamLight(noon, dc);
  assert.ok(day);
  assert.match(day.shown[0], /^Sunset [56]:\d\d PM$/);
  assert.match(day.shown[1], /^Sunrise 7:\d\d AM$/);
  assert.match(day.said, /^Sunset [56]:\d\d PM; Sunrise 7:\d\d AM\.$/);
  // Half an hour before sunset: the time till it, shown and said.
  const sunset = solarDay(noon, dc[1], dc[0]).sunset!;
  const soon = roamLight(sunset - 30 * 60_000, dc)!;
  assert.match(soon.shown[0], /^Sunset \d+:\d\d PM \(30 min\)$/);
  assert.match(soon.said, /^Sunset \d+:\d\d PM, in 30 minutes;/);
  // Just after sunset: tomorrow's sunrise first, then tomorrow's sunset.
  const after = roamLight(sunset + 60_000, dc)!;
  assert.match(after.shown[0], /^Sunrise /);
  assert.match(after.shown[1], /^Sunset /);
});

test("App: Broadcast is a tap within Roam; the leader leads a ride with no route, and one who opens the link follows", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // The share sheet opens before any await: the press's activation holds.
  assert.match(app, /const broadcastRoam = async \(\): Promise<string> => \{[^]*?const done = await shareLink\(navigator,/);
  const before = app.slice(app.indexOf("const broadcastRoam"), app.indexOf("const done = await shareLink(navigator,"));
  assert.doesNotMatch(before, /await /);
  assert.match(app, /leadConsent\(await roamRideId\(id\), lead\.token\);/);
  assert.match(app, /onBroadcast=\{canShare \? broadcastRoam : null\}/);
  assert.match(app, /const ROAM_FOLLOW = roamLinkFrom\(window\.location\.hash\);/);
  assert.match(app, /broadcast=\{\{ \.\.\.roamBroadcast, roam: true \}\}/);
  // It ends with the roam.
  assert.match(app, /const endRoam = \(\) => \{[^]*?setRoamBroadcast\(\(b\) => \(b\?\.leading \? null : b\)\);/);
});

test("sunrise and sunset: before dawn, today's sunrise then today's sunset; across the spring clock change, tomorrow's", () => {
  const dc: LonLat = [-77.04, 38.91];
  const sunrise = solarDay(Date.UTC(2026, 9, 22, 16, 0), dc[1], dc[0]).sunrise!;
  const early = roamLight(sunrise - 4 * 3_600_000, dc)!;
  assert.match(early.shown[0], /^Sunrise 7:\d\d AM$/);
  assert.match(early.shown[1], /^Sunset [56]:\d\d PM$/);
  // 2027-03-13 at 11:30 PM in Washington (04:30 UTC on the 14th), the night before clocks go forward: the 14th's sunrise.
  const night = Date.UTC(2027, 2, 14, 4, 30);
  const next = solarDay(Date.UTC(2027, 2, 14, 17, 0), dc[1], dc[0]).sunrise!;
  assert.equal(roamLight(night, dc)!.shown[0], `Sunrise ${lightClock(next)}`);
});

test("App: a Roam link opened in a tab already on the app follows it and keeps the plan; leading, a detour starts no other group", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const follow = roamLinkFrom\(window\.location\.hash\);\s*if \(follow\) \{\s*setRoamBroadcast\(\(b\) => \(b\?\.leading \? b : \{ \.\.\.follow, leading: false \}\)\);\s*return;\s*\}\s*const plan = decodePlan/);
  assert.match(app, /const rideGroupLine =\s*!roamBroadcast\?\.leading && \(goMode/);
});
