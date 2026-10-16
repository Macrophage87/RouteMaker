// Course export (PLAN.md, Import and export, Formats): FIT and TCX from the route shown, Ride's cues pinned to
// records, device profiles' budgets with what was trimmed said in one line, attribution per format, and the
// plan's points named by role (Start, Stop N, Finish), never by a saved place's label.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import { DEFAULT_PROFILE, DEVICE_PROFILES, deviceProfile, type DeviceProfile } from "./deviceProfiles.ts";
import {
  FIT_NAME_CREDIT,
  TCX_COURSE_NAME_CHARS,
  TCX_CUE_NAME_CHARS,
  abbreviateStreet,
  compileCourse,
  courseFileName,
  courseLine,
  courseName,
  thin,
} from "./course.ts";
import { TCX_NS, writeTcx } from "./tcx.ts";
import { at, sampleRoute } from "./courseTestRoute.ts";

const GENERIC = deviceProfile(DEFAULT_PROFILE);

test("the default device profile is generic, and every profile has a budget", () => {
  assert.equal(DEFAULT_PROFILE, "generic");
  assert.equal(GENERIC.maxCues, 200, "PLAN.md: defaulting to 200 course points");
  for (const p of DEVICE_PROFILES) {
    assert.ok(p.maxCues > 0 && p.maxPoints > 0 && p.cueNameChars > 0 && p.courseNameChars > 0, p.id);
    assert.equal(p.verified, null, "no profile has been checked on its device yet");
  }
  assert.equal(deviceProfile("nonsense").id, "generic");
});

test("cues are Ride's, in order, the start first and the finish last, each pinned to a record", () => {
  const course = compileCourse(sampleRoute(), GENERIC, "fit");
  assert.deepEqual(
    course.cues.map((c) => [c.type, c.name]),
    [
      ["start", "Start"],
      ["left", "17th St NW"],
      ["danger", "Florida Ave NW"],
      ["danger", "Dupont Cir"],
      ["stop", "Stop 1"],
      ["right", "Right"],
      ["note", "Busy road"],
      ["finish", "Finish"],
    ],
  );
  // The turn's full words are Ride's: the turn and the street alone.
  assert.equal(course.cues[1].text, "Left onto 17th Street Northwest.");
  // Pinned to the nearest record: 500 m along is vertex 50.
  assert.equal(course.records[course.cues[1].vertex].distM.toFixed(0), "500");
  assert.equal(course.cues[0].vertex, 0);
  assert.equal(course.cues[course.cues.length - 1].vertex, course.records.length - 1);
  // Times are the route's own pace from the fixed base: 600 s over the line.
  assert.ok(Math.abs(course.records[course.records.length - 1].timeS - 600) < 1e-6);
  // Elevations are the route profile's, as the GPX export writes them.
  assert.equal(course.records[0].ele, 20);
  assert.ok(Math.abs((course.records[150].ele ?? 0) - 35) < 0.5);
});

test("a via point is no cue, as in Ride", () => {
  const course = compileCourse(sampleRoute(), GENERIC, "fit", [1]);
  assert.ok(!course.cues.some((c) => c.type === "stop"));
});

test("the plan's points are named by role: a Home start or finish is Start and Finish, never its label", () => {
  // The rider's Home is a plan point like any other; nothing about it reaches the course but its position.
  const route = sampleRoute();
  for (const format of ["fit", "tcx"] as const) {
    const course = compileCourse(route, GENERIC, format);
    const names = course.cues.map((c) => c.name);
    assert.equal(names[0], "Start");
    assert.equal(names[names.length - 1], "Finish");
    assert.ok(!JSON.stringify(course).includes("Home"));
  }
  assert.ok(!writeTcx(compileCourse(route, GENERIC, "tcx")).includes("Home"));
});

test("street names are shortened for the unit's screen, and cut to the profile's length", () => {
  assert.equal(abbreviateStreet("R Street Northwest"), "R St NW");
  assert.equal(abbreviateStreet("Capital Crescent Trail"), "Capital Crescent Trl");
  const tcx = compileCourse(sampleRoute(), GENERIC, "tcx");
  for (const c of tcx.cues) assert.ok(Array.from(c.name).length <= TCX_CUE_NAME_CHARS, c.name);
  assert.equal(tcx.cues[2].name, "Florida Av", "cut to TCX's 10 characters, without a trailing space");
  const narrow: DeviceProfile = { ...GENERIC, cueNameChars: 6 };
  assert.ok(compileCourse(sampleRoute(), narrow, "fit").cues.every((c) => Array.from(c.name).length <= 6));
});

test("over the cue budget, the least important go first; start, finish, stops and Avoid warnings never", () => {
  const route = sampleRoute();
  const tight: DeviceProfile = { ...GENERIC, label: "Tight", maxCues: 5 };
  const course = compileCourse(route, tight, "fit");
  // 8 cues: the busy-road note goes, then the flagged crossing, then the unnamed turn.
  assert.deepEqual(
    course.cues.map((c) => c.type),
    ["start", "left", "danger", "stop", "finish"],
  );
  assert.equal(course.cues[2].name, "Dupont Cir", "the Avoid warning is kept, the flagged crossing is not");
  assert.equal(course.trim.cuesBefore, 8);
  assert.equal(course.trim.cuesKept, 5);
  assert.equal(course.trim.protectedOver, false);
  assert.equal(courseLine(course), "FIT course for Tight: kept 5 of 8 cues, least important left out.");
});

test("cues the course must keep are kept past the budget, and the line says to split the route", () => {
  const tiny: DeviceProfile = { ...GENERIC, label: "Tiny", maxCues: 2 };
  const course = compileCourse(sampleRoute(), tiny, "tcx");
  assert.deepEqual(course.cues.map((c) => c.type), ["start", "danger", "stop", "finish"]);
  assert.equal(course.trim.protectedOver, true);
  assert.match(courseLine(course), /^TCX course for Tiny: it keeps 4 cues it must not drop, more than the 2 the device shows; split the route in two/);
});

test("over the point budget the line is thinned, never moving a cue's record, and the line says so", () => {
  // A straight line thins to its ends and the cues' records.
  const few: DeviceProfile = { ...GENERIC, label: "Few", maxPoints: 20 };
  const course = compileCourse(sampleRoute(), few, "fit");
  assert.ok(course.records.length <= 20);
  assert.equal(course.records.length, 7, "the cues' records: 8 cues, the stop and the turn after it sharing one");
  const before = compileCourse(sampleRoute(), GENERIC, "fit");
  course.cues.forEach((c, i) => {
    const r = course.records[c.vertex];
    const o = before.records[before.cues[i].vertex];
    assert.deepEqual([r.lon, r.lat, r.distM], [o.lon, o.lat, o.distM], c.name);
  });
  assert.equal(courseLine(course), `FIT course for Few: thinned from 301 to ${course.records.length} points, within 3 ft (1 m) of the route.`);
  assert.equal(courseLine(before), "FIT course for Any bike computer: all 8 cues and 301 points fit.");
});

test("thinning keeps every vertex further than the tolerance from the line", () => {
  const zig: LonLat[] = [at(0), at(100, 0.5), at(200, 0), at(300, 30), at(400, 0)];
  assert.deepEqual(thin(zig, 1), [true, false, true, true, true]);
  assert.deepEqual(thin(zig, 50), [true, false, false, false, true]);
  assert.deepEqual(thin(zig, 50, new Set([2])), [true, false, true, false, true]);
});

test("the course name fits the format and profile; FIT carries the OSM credit in it where it fits", () => {
  const route = sampleRoute();
  assert.equal(courseName(route, TCX_COURSE_NAME_CHARS, "tcx"), "Default 1.9 mi");
  assert.equal(courseName(route, 15, "fit"), "Default 1.9 mi", "no room for the credit: PLAN.md's FIT carve-out");
  assert.equal(courseName(route, 32, "fit"), `Default route, 1.9 mi (3.0 km)`);
  assert.equal(courseName(route, 40, "fit"), `Default route, 1.9 mi (3.0 km)${FIT_NAME_CREDIT}`);
  assert.equal(courseFileName(route, "fit"), "routemaker-default-1_9mi.fit");
  assert.equal(courseFileName(route, "tcx"), "routemaker-default-1_9mi.tcx");
});

test("TCX: the schema's order, the attribution in Course/Notes, full cue words in CoursePoint/Notes", () => {
  const xml = writeTcx(compileCourse(sampleRoute(), GENERIC, "tcx"));
  assert.ok(xml.startsWith(`<?xml version="1.0" encoding="UTF-8"?>\n<TrainingCenterDatabase xmlns="${TCX_NS}">`));
  const course = xml.slice(xml.indexOf("<Course>"), xml.indexOf("</Course>"));
  const order = ["<Name>", "<Lap>", "<Track>", "<Notes>", "<CoursePoint>"].map((tag) => course.indexOf(tag));
  assert.deepEqual([...order].sort((a, b) => a - b), order, "Course_t's sequence");
  assert.match(course, /<Notes>Default route, 1\.9 mi \(3\.0 km\)\. Route data: © OpenStreetMap contributors \(ODbL\); USGS 3DEP\. Planned with RouteMaker\.<\/Notes>/);
  assert.match(course, /<CoursePoint>\s*<Name>17th St NW<\/Name>\s*<Time>2000-01-01T00:01:40Z<\/Time>\s*<Position>[\s\S]*?<\/Position>\s*<AltitudeMeters>[\d.]+<\/AltitudeMeters>\s*<PointType>Left<\/PointType>\s*<Notes>Left onto 17th Street Northwest\.<\/Notes>/);
  const types = [...course.matchAll(/<PointType>([^<]+)<\/PointType>/g)].map((m) => m[1]);
  assert.deepEqual(types, ["Generic", "Left", "Danger", "Danger", "Generic", "Right", "Generic", "Generic"]);
  // Every course point has a time and a position (required in TCX).
  const points = course.split("<CoursePoint>").slice(1);
  assert.ok(points.every((p) => p.includes("<Time>") && p.includes("<LatitudeDegrees>")));
  assert.equal((course.match(/<Trackpoint>/g) ?? []).length, 301);
  // Clean: no Author or Creator, and no clock.
  assert.ok(!/<Author|<Creator/.test(xml));
  assert.equal(writeTcx(compileCourse(sampleRoute(), GENERIC, "tcx")), xml, "byte-identical across runs");
});
