// Course export (PLAN.md, Import and export, Formats): FIT and TCX from the route shown, Ride's cues pinned to
// records, device profiles' budgets with what was trimmed said in one line, attribution per format, and the
// plan's points named by role (Start, Stop N, Finish), never by a saved place's label.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { haversineM, type LonLat } from "./geo.ts";
import { parseGpx } from "./gpx.ts";
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
import { TCX_CUE_TYPES, TCX_NS, escapeXml, writeTcx } from "./tcx.ts";
import { at, sampleRoute } from "./courseRoute.test.fixture.ts";
import { FIT_CUE_TYPES } from "./fit.ts";
import { cueRows } from "./cueSheetPdf.ts";

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
      ["note", "Florida Ave NW"],
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
  assert.equal(abbreviateStreet("service road beside East-West Highway"), "Svc Rd", "a unit has no room for the road beside");
  assert.equal(abbreviateStreet("sidewalk beside East-West Highway"), "Sidewalk");
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

test("only the cues never dropped are danger: a flagged crossing, which can be, is a note (Generic)", () => {
  for (const format of ["fit", "tcx"] as const) {
    const course = compileCourse(sampleRoute(), GENERIC, format);
    const florida = course.cues.find((c) => c.name.startsWith("Florida"))!;
    assert.equal(florida.type, "note", format);
    assert.equal(course.cues.find((c) => c.name === "Dupont Cir")!.type, "danger", format);
    // Every danger cue survives the tightest budget: dropped ones are never danger.
    const tight = compileCourse(sampleRoute(), { ...GENERIC, maxCues: 5 }, format);
    const kept = new Set(tight.cues.map((c) => c.text));
    for (const c of course.cues) if (c.type === "danger") assert.ok(kept.has(c.text), c.name);
  }
  assert.equal(TCX_CUE_TYPES.note, "Generic");
  assert.equal(TCX_CUE_TYPES.danger, "Danger");
});

test("over the byte budget the line is thinned further, past the point budget's tolerances, until it fits", () => {
  const full = compileCourse(sampleRoute(), GENERIC, "tcx");
  assert.equal(full.trim.bytes, new TextEncoder().encode(writeTcx(full)).length);
  assert.equal(full.trim.toleranceM, 0);
  // A budget the whole line does not fit: thinned (here a straight line) to the cues' records.
  const small: DeviceProfile = { ...GENERIC, label: "Small", maxBytes: Math.floor(full.trim.bytes / 2) };
  const course = compileCourse(sampleRoute(), small, "tcx");
  assert.ok(course.trim.bytes <= small.maxBytes, `${course.trim.bytes}`);
  assert.equal(course.trim.bytes, new TextEncoder().encode(writeTcx(course)).length);
  assert.ok(course.records.length < full.records.length);
  assert.equal(course.cues.length, full.cues.length);
  // A budget nothing fits: as thin as it goes, and the line says it is still too large.
  const tiny = compileCourse(sampleRoute(), { ...small, maxBytes: 100 }, "fit");
  assert.ok(tiny.trim.toleranceM > 10);
  assert.match(courseLine(tiny), /; still larger than the 1 KB it takes\.$/);
  for (const p of DEVICE_PROFILES) assert.ok(p.maxBytes >= 4_000_000, p.id);
});

test("where the cues the course must keep pass the budget alone, nothing is dropped and the line says to split", () => {
  const tiny: DeviceProfile = { ...GENERIC, label: "Tiny", maxCues: 3 };
  const course = compileCourse(sampleRoute(), tiny, "tcx");
  // Start, the Avoid warning, the stop and the finish must stay; the turns are not given up for a course that cannot fit.
  assert.equal(course.cues.length, 8);
  assert.equal(course.trim.protectedCues, 4);
  assert.equal(course.trim.protectedOver, true);
  assert.equal(courseLine(course), "TCX course for Tiny: 4 of its cues must be kept, more than the 3 the device shows; split the route in two.");
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
  // A shorter wording that leaves room for the credit comes before a longer one without it.
  assert.equal(courseName(route, 32, "fit"), `Default 1.9 mi (3.0 km)${FIT_NAME_CREDIT}`);
  assert.equal(courseName(route, 22, "fit"), `Default 1.9 mi${FIT_NAME_CREDIT}`);
  assert.equal(courseName(route, 40, "fit"), `Default route, 1.9 mi (3.0 km)${FIT_NAME_CREDIT}`);
  assert.equal(courseName(route, 32, "tcx"), "Default route, 1.9 mi (3.0 km)", "TCX's credit is in Course/Notes");
  // Plain ASCII: a unit's font may have no ©.
  assert.equal(FIT_NAME_CREDIT, " (c) OSM");
  assert.match(FIT_NAME_CREDIT, /^[\x20-\x7e]+$/);
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
  assert.deepEqual(types, ["Generic", "Left", "Generic", "Danger", "Generic", "Right", "Generic", "Generic"]);
  // Every course point has a time and a position (required in TCX).
  const points = course.split("<CoursePoint>").slice(1);
  assert.ok(points.every((p) => p.includes("<Time>") && p.includes("<LatitudeDegrees>")));
  assert.equal((course.match(/<Trackpoint>/g) ?? []).length, 301);
  // Clean: no Author or Creator, and no clock.
  assert.ok(!/<Author|<Creator/.test(xml));
  assert.equal(writeTcx(compileCourse(sampleRoute(), GENERIC, "tcx")), xml, "byte-identical across runs");
});

test("TCX text holds only XML characters: controls, U+FFFE, U+FFFF and lone surrogates go; pairs stay", () => {
  assert.equal(escapeXml("a\u0001b\uFFFEc\uFFFFd"), "abcd");
  assert.equal(escapeXml("x\uD800y\uDC00z"), "xyz");
  assert.equal(escapeXml("bike \uD83D\uDEB2 & <go>"), "bike \uD83D\uDEB2 &amp; &lt;go&gt;");
  assert.equal(escapeXml("tab\tnew\nline"), "tab\tnew\nline");
  // Written as escapes, not as the characters themselves.
  assert.ok(!/[\uFFFE\uFFFF]/.test(readFileSync(new URL("./tcx.ts", import.meta.url), "utf8")));
});

test("thinning a 7,500-point reference ride to a small budget keeps every dropped point within the tolerance", () => {
  // fixtures/reference-routes: the largest reference track, thinned as a 2,000-point device would have it.
  const text = readFileSync(new URL("../../../fixtures/reference-routes/rural-group-loco-30.gpx", import.meta.url), "utf8");
  const line = parseGpx(text).tracks[0].segments.flat();
  assert.ok(line.length > 7000);
  const small: DeviceProfile = { ...GENERIC, label: "Small", maxPoints: 2000 };
  const course = compileCourse(sampleRoute({ geometry: { type: "LineString", coordinates: line }, description: [], leg_ends: [] }), small, "fit");
  assert.ok(course.records.length <= 2000, `${course.records.length}`);
  const t = course.trim.toleranceM;
  assert.ok(t > 0 && t <= 10);
  // Every original vertex lies within the tolerance of the thinned line's segment that spans it.
  const kept = course.records.map((r) => [r.lon, r.lat] as LonLat);
  const keptAt = course.records.map((r) => r.distM);
  let seg = 0;
  let along = 0;
  line.forEach((p, i) => {
    if (i > 0) along += haversineM(line[i - 1], p);
    while (seg < kept.length - 2 && keptAt[seg + 1] <= along) seg += 1;
    const d = offsetFrom(p, kept[seg], kept[seg + 1]);
    assert.ok(d <= t + 1e-6, `vertex ${i} is ${d.toFixed(2)} m off`);
  });
});

/** Metres from p to the segment a-b on a flat local projection, as course.ts measures it. */
function offsetFrom(p: LonLat, a: LonLat, b: LonLat): number {
  const kx = 111_320 * Math.cos((a[1] * Math.PI) / 180);
  const ky = 110_574;
  const [px, py, bx, by] = [(p[0] - a[0]) * kx, (p[1] - a[1]) * ky, (b[0] - a[0]) * kx, (b[1] - a[1]) * ky];
  const len = bx * bx + by * by;
  const s = len > 0 ? Math.max(0, Math.min(1, (px * bx + py * by) / len)) : 0;
  return Math.hypot(px - s * bx, py - s * by);
}

test("a jog (Q Street NW, 2026-10-16): each turn its own course point, a bear a slight turn; the cue sheet one row saying both", () => {
  const stretch = (from: number, to: number, text: string, extra: object) => ({ kind: "stretch", from_m: from, to_m: to, from_mi: 0, to_mi: 0, street: null, tier: 2, facility: null, turn: null, text, ...extra });
  const turn = (movement: string, onto: string) => ({ movement, onto, control: null, severity: null });
  const route = sampleRoute({
    description: [
      stretch(0, 500, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(500, 530, "Right onto 6th Street Northwest.", { street: "6th Street Northwest", turn: turn("right", "6th Street Northwest") }),
      stretch(530, 3000, "Bear left onto Rhode Island Avenue Northwest.", { street: "Rhode Island Avenue Northwest", turn: turn("bear_left", "Rhode Island Avenue Northwest") }),
    ],
    leg_ends: [300],
  } as never);
  const course = compileCourse(route, GENERIC, "fit");
  assert.deepEqual(
    course.cues.map((c) => [c.type, c.text]),
    [
      ["start", "Start."],
      ["right", "Right onto 6th Street Northwest."],
      ["slight_left", "Bear left onto Rhode Island Avenue Northwest."],
      ["finish", "The end of the route."],
    ],
  );
  assert.equal(FIT_CUE_TYPES.slight_left, 19);
  assert.equal(FIT_CUE_TYPES.slight_right, 21);
  assert.equal(TCX_CUE_TYPES.slight_left, "Left");
  const rows = cueRows(route, "rider").filter((r) => r.type !== "start" && r.type !== "finish");
  assert.deepEqual(
    rows.map((r) => [r.turn, r.road, r.notes]),
    [["Right", "6th Street Northwest", "Right onto 6th Street Northwest, then immediately bear left onto Rhode Island Avenue Northwest."]],
  );
});
