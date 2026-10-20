// Light times on the route (lib/lightTimes.ts): NOAA's solar formulas, where the rider is, and the hour rule.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathLengthM, type LonLat } from "./geo.ts";
import {
  LIGHT_WINDOW_MS,
  lightClock,
  lightLine,
  lightMarkerLabel,
  underControls,
  lightMarks,
  pointAlong,
  routeLightMarks,
  sameLightMarks,
  solarDay,
} from "./lightTimes.ts";

// Washington, DC (the White House area).
const DC = { lat: 38.8951, lon: -77.0364 };

// NOAA Solar Calculator values for Washington, DC (computed with NOAA's algorithm by astral 3.2), in the
// region's time: civil dawn, sunrise, sunset, civil dusk. Two either side of each clock change. These
// formulas were also compared with PyEphem (an independent ephemeris) in review; its figures are not
// pinned here. The one-minute tolerance is the accuracy NOAA states for its calculator.
const KNOWN: Array<[string, string, string, string, string]> = [
  ["2026-03-07", "06:04:41-05:00", "06:31:48-05:00", "18:06:58-05:00", "18:34:06-05:00"],
  ["2026-03-08", "07:03:12-04:00", "07:30:17-04:00", "19:07:59-04:00", "19:35:07-04:00"], // EDT begins
  ["2026-06-21", "05:10:36-04:00", "05:43:19-04:00", "20:36:42-04:00", "21:09:24-04:00"],
  ["2026-10-16", "06:51:26-04:00", "07:18:51-04:00", "18:27:50-04:00", "18:55:13-04:00"],
  ["2026-11-01", "06:07:27-05:00", "06:35:37-05:00", "17:07:13-05:00", "17:35:23-05:00"], // EST again
  ["2026-12-21", "06:52:50-05:00", "07:23:24-05:00", "16:49:14-05:00", "17:19:48-05:00"],
];

test("NOAA's light times for Washington, DC, across the clock changes, within a minute", () => {
  for (const [date, dawn, rise, set, dusk] of KNOWN) {
    // Any moment of the region's day gives that day: here 10:00 local.
    const day = solarDay(Date.parse(`${date}T10:00:00${dawn.slice(-6)}`), DC.lat, DC.lon);
    const want = { civil_dawn: dawn, sunrise: rise, sunset: set, civil_dusk: dusk };
    for (const [kind, local] of Object.entries(want)) {
      const got = day[kind as keyof typeof day];
      assert.ok(got !== null, `${date} ${kind}`);
      const off = Math.abs(got - Date.parse(`${date}T${local}`)) / 1000;
      assert.ok(off <= 60, `${date} ${kind} is ${off.toFixed(0)} s out`);
    }
  }
  // Late evening is still the same local day (00:30 UTC the next day).
  const late = solarDay(Date.parse("2026-06-21T23:30:00-04:00"), DC.lat, DC.lon);
  assert.equal(lightClock(late.sunset as number), "8:36 PM");
  assert.equal(lightClock(solarDay(Date.parse("2026-12-21T12:00:00-05:00"), DC.lat, DC.lon).sunset as number), "4:49 PM");
});

// Due east across the District and beyond: about 26 km.
const LINE: LonLat[] = [
  [-77.05, 38.89],
  [-76.95, 38.89],
  [-76.75, 38.89],
];
const LENGTH = pathLengthM(LINE);

test("the point a distance along the route", () => {
  assert.deepEqual(pointAlong(LINE, 0), LINE[0]);
  assert.deepEqual(pointAlong(LINE, LENGTH + 500), LINE[2]);
  const first = pathLengthM(LINE.slice(0, 2));
  const [lon, lat] = pointAlong(LINE, first / 2) as LonLat;
  assert.ok(Math.abs(lon - -77.0) < 1e-6 && Math.abs(lat - 38.89) < 1e-9);
  const [lon2] = pointAlong(LINE, first + (LENGTH - first) / 2) as LonLat;
  assert.ok(Math.abs(lon2 - -76.85) < 1e-6);
  assert.equal(pointAlong([], 10), null);
});

const ride = (departLocal: string, minutes: number) => ({
  line: LINE,
  distanceM: LENGTH,
  durationS: minutes * 60,
  departMs: Date.parse(departLocal),
});

test("a ride through dusk: sunset and the end of civil twilight where the rider will be", () => {
  // 16 Oct 2026, 17:30 EDT for 90 minutes: sunset 18:27, civil dusk 18:55, both on the ride.
  const marks = lightMarks(ride("2026-10-16T17:30:00-04:00", 90));
  assert.deepEqual(marks.map((m) => [m.kind, m.where]), [["sunset", "during"], ["civil_dusk", "during"]]);
  const [sunset, dusk] = marks;
  // At the rider's pace, sunset comes about 58 of the 90 minutes in; a little earlier for being east.
  const share = (sunset.alongM as number) / LENGTH;
  assert.ok(share > 0.6 && share < 0.66, String(share));
  assert.ok((dusk.alongM as number) > (sunset.alongM as number));
  assert.ok(sunset.point && Math.abs(sunset.point[1] - 38.89) < 1e-9);
  const line = lightLine(marks) as string;
  assert.match(line, /^Sunset 6:2\d PM near mile \d+\.\d \(\d+\.\d km\); civil twilight ends 6:5\d PM near mile \d+\.\d \(\d+\.\d km\)\.$/);
  assert.match(lightMarkerLabel(sunset), /^Sunset 6:2\d PM, where you will be near mile \d+\.\d \(\d+\.\d km\)$/);
});

test("within about an hour after arriving: said, not marked; only what is still ahead", () => {
  // Arriving 17:40 EDT: sunset 47 minutes later. Both of the dusk events are said, after the ride.
  const after = lightMarks(ride("2026-10-16T17:00:00-04:00", 40));
  assert.deepEqual(after.map((m) => [m.kind, m.where, m.point]), [["sunset", "after", null], ["civil_dusk", "after", null]]);
  assert.match(lightLine(after) as string, /^Sunset 6:2[78] PM, after you arrive; civil twilight ends 6:5[56] PM, after you arrive\.$/);
  // Arriving 17:20: sunset over an hour off. Nothing.
  assert.deepEqual(lightMarks(ride("2026-10-16T16:40:00-04:00", 40)), []);
  // Leaving 19:50, after civil dusk: what has passed is never said. Nothing.
  assert.deepEqual(lightMarks(ride("2026-10-16T19:50:00-04:00", 30)), []);
  // Leaving 18:40, between sunset and civil dusk: the end of civil twilight only.
  const dusk = lightMarks(ride("2026-10-16T18:40:00-04:00", 30));
  assert.deepEqual(dusk.map((m) => [m.kind, m.where]), [["civil_dusk", "during"]]);
  // The owner's example: civil twilight at 6:51, sunrise 7:18. Leaving 7:00, sunrise only; at 7:30, nothing.
  assert.deepEqual(lightMarks(ride("2026-10-16T07:00:00-04:00", 60)).map((m) => m.kind), ["sunrise"]);
  assert.deepEqual(lightMarks(ride("2026-10-16T07:30:00-04:00", 60)), []);
  // Midday and the middle of the night: nothing.
  assert.deepEqual(lightMarks(ride("2026-10-16T12:00:00-04:00", 60)), []);
  assert.deepEqual(lightMarks(ride("2026-10-17T01:00:00-04:00", 60)), []);
  assert.equal(lightLine([]), null);
  assert.equal(LIGHT_WINDOW_MS, 3_600_000);
});

test("a ride at dawn: civil dawn and sunrise, across the end of daylight saving time", () => {
  // 16 Oct 2026, 06:20 EDT for 50 minutes: civil dawn 06:51 on the ride, sunrise 07:18 after it.
  const marks = lightMarks(ride("2026-10-16T06:20:00-04:00", 50));
  assert.deepEqual(marks.map((m) => [m.kind, m.where]), [["civil_dawn", "during"], ["sunrise", "after"]]);
  assert.match(lightLine(marks) as string, /^Civil twilight begins 6:5\d AM near mile \d+\.\d \(\d+\.\d km\); sunrise 7:1\d AM, after you arrive\.$/);
  // Sunday 1 Nov 2026, the first EST morning: 06:00 EST for an hour, both on the ride.
  const nov = lightMarks(ride("2026-11-01T06:00:00-05:00", 60));
  assert.deepEqual(nov.map((m) => m.kind), ["civil_dawn", "sunrise"]);
  assert.ok(nov.every((m) => m.where === "during"));
  assert.match(lightClock(nov[1].at), /^6:3\d AM$/);
});

test("only the first twilight after setting off, however long the ride", () => {
  const marks = lightMarks(ride("2026-06-21T20:00:00-04:00", 10 * 60));
  assert.deepEqual(marks.map((m) => m.kind), ["sunset", "civil_dusk"]);
  // Leaving late at night: the next dawn, when it comes within the ride or the hour after.
  assert.deepEqual(lightMarks(ride("2026-06-22T04:30:00-04:00", 60)).map((m) => m.kind), ["civil_dawn", "sunrise"]);
});

test("a planned route: leaving now, not on a transit or bikeshare plan, nor for another ride time", () => {
  const route = { geometry: { coordinates: LINE }, distance_m: LENGTH, duration_s: 90 * 60 };
  const now = Date.parse("2026-10-16T17:30:00-04:00"); // a Friday, in the evening rush
  assert.equal(routeLightMarks(route, now, null).length, 2);
  assert.equal(routeLightMarks(route, now, "weekday_rush").length, 2);
  assert.deepEqual(routeLightMarks(route, now, "weekend"), []);
  // Night runs into dawn and from dusk whatever the day: leaving now, as with "when I'm planning".
  assert.equal(routeLightMarks(route, now, "night").length, 2);
  assert.deepEqual(routeLightMarks({ ...route, transit: {} }, now, null), []);
  assert.deepEqual(routeLightMarks({ ...route, bikeshare: {} }, now, null), []);
  assert.deepEqual(routeLightMarks({ ...route, duration_s: 0 }, now, null), []);
  assert.deepEqual(routeLightMarks(null, now, null), []);
});

test("the same marks are kept while what they say has not changed", () => {
  const a = lightMarks(ride("2026-10-16T17:30:00-04:00", 90));
  const b = lightMarks(ride("2026-10-16T17:30:00-04:00", 90));
  assert.ok(sameLightMarks(a, b));
  assert.ok(sameLightMarks([], []));
  assert.ok(!sameLightMarks(a, lightMarks(ride("2026-10-16T17:40:00-04:00", 90))));
  assert.ok(!sameLightMarks(a, a.slice(1)));
});

test("how far along, miles first", async () => {
  const { formatMilePost } = await import("./format.ts");
  assert.equal(formatMilePost(19_956), "mile 12.4 (20.0 km)");
  assert.equal(formatMilePost(100), "the start");
});

test("wired: marks on Plan's map only, the line in the route summary, no new control", () => {
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  const app = read("../App.tsx");
  assert.match(app, /routeLightMarks\(shown, minute, dials\.when \?\? null\)/);
  assert.match(app, /useMinute\(shown !== null && !riding && \(mode === "plan" \|\| mode === "go"\)\)/);
  assert.match(app, /if \(!sameLightMarks\(lightKept\.current, next\)\) lightKept\.current = next;/);
  assert.match(app, /lightMarks=\{riding \|\| mode !== "plan" \? null : light\}/);
  const panel = read("../app/RoutePanel.tsx");
  assert.match(panel, /const lightText = lightLine\(light\);/);
  assert.match(panel, /key: "light", className: "hint light-times"/);
  const view = read("../MapView.tsx");
  assert.match(view, /element\.className = "light-marker";[\s\S]*setAttribute\("role", "img"\);[\s\S]*setAttribute\("aria-label", lightMarkerLabel\(mark\)\)/);
  assert.match(view, /filter\(\(mark\) => mark\.where === "during" && mark\.point\)/);
  // A label only: it never takes the map's clicks or drags.
  const light = view.slice(view.indexOf("const lightDrawn"), view.indexOf("An infrequent departure's label"));
  assert.doesNotMatch(light, /addEventListener/);
  assert.match(read("../styles.css"), /\.light-marker \{\n  pointer-events: none;\n\}/);
});

test("a light marker under the map's controls (the scale bar) is not drawn but keeps its name; one clear of them is", () => {
  const scale = { left: 900, top: 700, right: 1000, bottom: 720 };
  assert.equal(underControls({ left: 950, top: 690, right: 1010, bottom: 710 }, [scale]), true);
  assert.equal(underControls({ left: 700, top: 690, right: 800, bottom: 710 }, [scale]), false);
  assert.equal(underControls({ left: 950, top: 650, right: 1010, bottom: 700 }, [scale]), false, "touching is not under");
  assert.match(readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8"), /element\.classList\.toggle\("under-controls", underControls\(/);
  assert.match(readFileSync(new URL("../styles.css", import.meta.url), "utf8"), /\.light-marker\.under-controls span \{\n  visibility: hidden;\n\}/);
});

test("Ride mode's corner: the light times within the hour rule, for the ride still to go (the owner, 2026-10-19)", async () => {
  const { rideLightCorner } = await import("./lightTimes.ts");
  const line: LonLat[] = [
    [DC.lon, DC.lat],
    [DC.lon + 0.05, DC.lat],
  ];
  const lengthM = pathLengthM(line);
  const model = { coordinates: line, along: Float64Array.from([0, lengthM]), lengthM };
  // 2026-10-16, sunset 6:27:50 PM: at 6:00 PM, 20 minutes to go, both dusk events, short and in words.
  const six = Date.parse("2026-10-16T18:00:00-04:00");
  const corner = rideLightCorner(model, 0, 20 * 60, six);
  assert.ok(corner);
  assert.equal(corner.shown.length, 2);
  assert.match(corner.shown[0], /^Sunset 6:2\d PM \(2\d min\)$/);
  assert.match(corner.shown[1], /^Twilight 6:5\d PM \(5\d min\)$/);
  assert.match(corner.said, /^Sunset 6:2\d PM, in 2\d minutes; civil twilight ends 6:5\d PM, in 5\d minutes\.$/);
  // After sunset: only what is still ahead.
  assert.deepEqual(rideLightCorner(model, lengthM / 2, 10 * 60, Date.parse("2026-10-16T18:40:00-04:00"))?.shown.length, 1);
  // Midday: nothing, so the corner says Ride mode.
  assert.equal(rideLightCorner(model, 0, 20 * 60, Date.parse("2026-10-16T12:00:00-04:00")), null);
  // Morning, 6:00 AM: civil dawn 6:51 AM within the hour, then sunrise.
  assert.match(rideLightCorner(model, 0, 10 * 60, Date.parse("2026-10-16T06:00:00-04:00"))?.said ?? "", /^Civil twilight begins 6:5\d AM, in 5\d minutes; sunrise 7:1\d AM, in 1 hour 1\d minutes\.$/);
});
