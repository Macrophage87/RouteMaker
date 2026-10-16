// Saved routes, verbatim GPX and the closure check (v0.7.0 plan: "Discord sign-in on, with saved settings and
// routes" item 3, and "GPX export as close to identical as possible, closure warning first").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse } from "./api.ts";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { parseGpx } from "./gpx.ts";
import { readGpx } from "./gpxImport.ts";
import { trackGpx, verbatimDownload, verbatimFileName } from "./gpxVerbatim.ts";
import {
  MAX_SAVED,
  defaultRouteName,
  differenceLine,
  differsTooMuch,
  gpxSave,
  planSave,
  RESTORED_SAID,
  UNCHANGED_SAID,
  VERSIONS_MAX,
  afterDelete,
  afterRename,
  saveAsVersion,
  listVersions,
  restoreVersion,
  rowDetails,
  saveRoute,
  versionDetails,
  versionOf,
} from "./savedRoutes.ts";
import {
  CHECK_MAX_POINTS,
  anywayLabel,
  checkClosures,
  closedStretches,
  closureHeading,
  spliceDetours,
  thinForCheck,
} from "./closureCheck.ts";

const FILE = `<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="Some Other App">
  <metadata><name>Thursday Mass Ride</name></metadata>
  <wpt lat="38.8977" lon="-77.0365"><name>Meet at the Ellipse</name></wpt>
  <trk><name>Thursday Mass Ride</name><trkseg>
    <trkpt lat="38.8976500" lon="-77.0365100"><ele>17.25</ele></trkpt>
    <trkpt lat="38.8990123" lon="-77.0331234"><ele>18.5</ele></trkpt>
    <trkpt lat="38.9010000" lon="-77.0300000"/>
    <trkpt lat="38.9030456" lon="-77.0270789"><ele>21</ele></trkpt>
  </trkseg></trk>
</gpx>
`;

test("a save offers 'Start to End' and keeps the line exactly as planned", () => {
  assert.equal(defaultRouteName("Union Station", "Capitol Hill"), "Union Station to Capitol Hill");
  assert.equal(defaultRouteName("", null), "Start to End");
  const route = {
    geometry: { type: "LineString", coordinates: [[-77.0123456, 38.9], [-77.01, 38.91]] },
    distance_m: 1234.5,
    candidates: [{}],
    avoid_alternate: {},
  } as unknown as RouteResponse;
  const points: LonLat[] = [[-77.0123456, 38.9], [-77.01, 38.91]];
  const body = planSave("Commute", route, points, "default", startDials("default"));
  assert.deepEqual(body.line, [[-77.0123456, 38.9], [-77.01, 38.91]]);
  assert.equal(body.distance_m, 1234.5);
  assert.equal(body.answer?.candidates, null);
  assert.equal(body.answer?.avoid_alternate, null);
  assert.match(body.inputs.hash, /preset=default/);
  assert.equal(MAX_SAVED, 200);
});

test("Update route is offered only past 5% in distance", () => {
  assert.equal(differsTooMuch(10_000, 10_500), false);
  assert.equal(differsTooMuch(10_000, 10_501), true);
  assert.equal(differsTooMuch(10_000, 9_400), true);
  assert.equal(differenceLine(10_000, 11_000), "Today's map plans this route 0.6 mi (1.0 km) longer.");
  assert.match(rowDetails({ distance_m: 7600, created_at: "2026-10-15T12:00:00Z", source: "gpx" }), /^4\.7 mi \(7\.6 km\) · GPX file · Saved Oct 15, 2026$/);
});

test("a save that is refused for the cap says so", async () => {
  const full = (async () => new Response(JSON.stringify({ error: "You have 200 saved routes.", code: "full" }), { status: 409 })) as unknown as typeof fetch;
  const outcome = await saveRoute("https://x.test", gpxSave("x", FILE, [[-77, 38.9], [-77.1, 38.8]], [], "default", startDials("default")), full, "");
  assert.deepEqual(outcome, { ok: false, full: true, message: "You have 200 saved routes." });
});

test("saved again under its own name in Plan is a new version; another name or Go is a new route", () => {
  const open = { id: 7, name: "Commute" };
  assert.equal(versionOf(open, " Commute ", true), 7);
  assert.equal(versionOf(open, "Commute 2", true), undefined);
  assert.equal(versionOf(open, "Commute", false), undefined);
  assert.equal(versionOf(null, "Commute", true), undefined);
});

test("a save as a version says whether one was kept", async () => {
  const sent: RequestInit[] = [];
  const post = (async (_url: string, init: RequestInit) => {
    sent.push(init);
    return new Response(JSON.stringify({ id: 7, name: "Commute", versioned: false }), { status: 200 });
  }) as unknown as typeof fetch;
  const body = { ...gpxSave("Commute", FILE, [[-77, 38.9], [-77.1, 38.8]], [], "default", startDials("default")), version_of: 7 };
  const outcome = await saveRoute("https://x.test", body, post, "csrftoken=abc");
  assert.ok(outcome.ok && outcome.versioned === false && outcome.route.id === 7);
  assert.equal(JSON.parse(String(sent[0].body)).version_of, 7);
});

test("a version of a route no longer in the account is saved as a new route", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const post = (async (_url: string, init: RequestInit) => {
    const sent = JSON.parse(String(init.body)) as Record<string, unknown>;
    bodies.push(sent);
    return sent.version_of !== undefined
      ? new Response(JSON.stringify({ error: "That saved route is not in your account.", code: "not_found" }), { status: 404 })
      : new Response(JSON.stringify({ id: 9, name: "Commute" }), { status: 201 });
  }) as unknown as typeof fetch;
  const body = gpxSave("Commute", FILE, [[-77, 38.9], [-77.1, 38.8]], [], "default", startDials("default"));
  const outcome = await saveAsVersion("https://x.test", body, 7, post, "");
  assert.ok(outcome.ok && outcome.route.id === 9 && outcome.versioned === undefined);
  assert.deepEqual(bodies.map((b) => b.version_of), [7, undefined]);
  // Any other refusal is said, not retried.
  const full = (async () => new Response(JSON.stringify({ error: "Full.", code: "full" }), { status: 409 })) as unknown as typeof fetch;
  assert.deepEqual(await saveAsVersion("https://x.test", body, 7, full, ""), { ok: false, full: true, message: "Full." });
});

test("the saved route on screen follows My routes' rename and is forgotten when deleted", () => {
  const open = { id: 7, name: "Commute" };
  assert.deepEqual(afterRename(open, 7, " Work run "), { id: 7, name: "Work run" });
  assert.equal(afterRename(open, 8, "Other"), open);
  assert.equal(afterDelete(open, 7), null);
  assert.equal(afterDelete(open, 8), open);
  // Renamed, saving under the new name is a version of it still.
  assert.equal(versionOf(afterRename(open, 7, "Work run"), "Work run", true), 7);
});

test("saved again unchanged: a file says its file has not changed", () => {
  assert.match(UNCHANGED_SAID("Thursday", "gpx"), /this route's file hasn't changed/);
  assert.match(UNCHANGED_SAID("Commute"), /nothing changed/);
});

test("a version's line: date, distance in US units first, and what changed", () => {
  assert.match(versionDetails({ saved_at: "2026-10-15T12:00:00Z", distance_m: 7600, change: "Stop added" }), /^Oct 15, 2026 · 4\.7 mi \(7\.6 km\) · Stop added$/);
  assert.match(versionDetails({ saved_at: "2026-10-15T12:00:00Z", distance_m: 7600, change: "" }), /^Oct 15, 2026 · 4\.7 mi \(7\.6 km\)$/);
  assert.match(RESTORED_SAID("Commute", { saved_at: "2026-10-12T12:00:00Z" }), /^Restored the version of "Commute" from Oct 12, 2026 as its latest/);
});

test("versions are listed and restored through the owner's own routes", async () => {
  const urls: string[] = [];
  const answer = (body: unknown, status = 200) =>
    (async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify(body), { status });
    }) as unknown as typeof fetch;
  const list = [{ id: null, saved_at: "2026-10-15T12:00:00Z", distance_m: 10, source: "plan", change: "Stop added" }];
  assert.deepEqual(await listVersions("https://x.test", 7, answer({ versions: list, max: VERSIONS_MAX })), list);
  assert.equal(await listVersions("https://x.test", 8, answer({ error: "not found" }, 404)), null);
  const restored = await restoreVersion("https://x.test", 7, 3, answer({ id: 7, name: "Commute" }), "csrftoken=abc");
  assert.equal(restored?.id, 7);
  assert.equal(await restoreVersion("https://x.test", 7, 3, answer({}, 404), ""), null);
  assert.deepEqual(urls, [
    "https://x.test/api/me/routes/7/versions",
    "https://x.test/api/me/routes/8/versions",
    "https://x.test/api/me/routes/7/versions/3/restore",
    "https://x.test/api/me/routes/7/versions/3/restore",
  ]);
});

test("round trip: an opened GPX file exports as the same file, every point, elevation and name", async () => {
  const opened = await readGpx(new Blob([FILE]));
  assert.ok(opened.ok);
  const plan = opened.ok ? opened.plan : null;
  assert.deepEqual(plan?.verbatim?.track, [
    [-77.03651, 38.89765, 17.25],
    [-77.0331234, 38.8990123, 18.5],
    [-77.03, 38.901],
    [-77.0270789, 38.9030456, 21],
  ]);
  const download = verbatimDownload(plan?.verbatim, false, plan?.name);
  assert.equal(download?.text, FILE);
  assert.equal(download?.fileName, "Thursday Mass Ride.gpx");
  const again = parseGpx(download!.text);
  assert.deepEqual(again.tracks[0].segments, parseGpx(FILE).tracks[0].segments);
  assert.deepEqual(again.tracks[0].elevations, [[17.25, 18.5, null, 21]]);
  assert.equal(again.waypoints[0].name, "Meet at the Ellipse");
  // Edited, the route on screen is written instead.
  assert.equal(verbatimDownload(plan?.verbatim, true, plan?.name), null);
  // A saved GPX route keeps the text byte for byte.
  const body = gpxSave("Thursday", FILE, plan!.verbatim!.track, plan!.points, "mass-ride", startDials("mass-ride"));
  assert.equal(body.gpx, FILE);
  assert.equal(body.source, "gpx");
  assert.deepEqual(body.line, plan!.verbatim!.track);
  assert.equal(verbatimFileName('a/b:"c"'), "a b c.gpx");
});

test("a file rerouted round closures is written from its kept line, elevations where it had them", () => {
  const text = trackGpx("Ride", [[-77.0365, 38.8976, 17.25], [-77.03, 38.9]]);
  const file = parseGpx(text);
  assert.deepEqual(file.tracks[0].segments[0], [[-77.0365, 38.8976], [-77.03, 38.9]]);
  assert.deepEqual(file.tracks[0].elevations, [[17.3, null]]);
  assert.equal(verbatimDownload({ text: null, track: [[-77.0365, 38.8976], [-77.03, 38.9]] }, false, "Ride")?.fileName, "Ride.gpx");
});

// ---- closures ----

const LINE: [number, number, number][] = Array.from({ length: 41 }, (_, i) => [-77.04 + i * 0.001, 38.9, 10 + i]);

test("the line is thinned to the check's limit, each point traced to the full line", () => {
  const long = Array.from({ length: 25_001 }, (_, i) => [-77 + i * 1e-6, 38.9] as LonLat);
  const thin = thinForCheck(long);
  assert.ok(thin.line.length <= CHECK_MAX_POINTS);
  assert.equal(thin.index[0], 0);
  assert.equal(thin.index[thin.index.length - 1], 25_000);
  assert.deepEqual(thinForCheck(LINE).index, LINE.map((_, i) => i));
});

test("the dialog names the closures and the choices fit what it was for", () => {
  assert.equal(closureHeading(1), "This route goes through 1 closure");
  assert.equal(closureHeading(2), "This route goes through 2 closures");
  assert.equal(anywayLabel("ride"), "Ride it anyway");
  assert.equal(anywayLabel("open"), "Ride it anyway");
  assert.equal(anywayLabel("download"), "Download anyway");
});

test("only the closed stretches are replaced; the rest stays verbatim", () => {
  // A closure from about 0.75 km to 1.2 km along a 3.4 km line (vertices every ~86.6 m).
  const stretches = closedStretches(LINE, [{ from_m: 750, to_m: 1200 }], LINE.map((_, i) => i));
  assert.equal(stretches.length, 1);
  const { before, after } = stretches[0];
  assert.ok(before >= 7 && before <= 8, `before ${before}`);
  assert.ok(after >= 14 && after <= 15, `after ${after}`);
  const detour: LonLat[] = [[LINE[before][0], LINE[before][1]], [LINE[before][0], 38.905], [LINE[after][0], 38.905], [LINE[after][0], LINE[after][1]]];
  const spliced = spliceDetours(LINE, stretches, [detour]);
  // Everything up to and including `before`, and from `after` on, is the very same vertex.
  assert.deepEqual(spliced.slice(0, before + 1), LINE.slice(0, before + 1));
  assert.deepEqual(spliced.slice(before + 3), LINE.slice(after));
  assert.deepEqual(spliced.slice(before + 1, before + 3), [[LINE[before][0], 38.905], [LINE[after][0], 38.905]]);
  // No way round: the stretch stays as it was.
  assert.deepEqual(spliceDetours(LINE, stretches, [null]), LINE);
  // Two closures that touch are one stretch.
  assert.equal(closedStretches(LINE, [{ from_m: 750, to_m: 1000 }, { from_m: 1010, to_m: 1200 }], LINE.map((_, i) => i)).length, 1);
});

test("the check is a POST of the line, and a failure never holds the route up", async () => {
  let sent: unknown;
  const ok = (async (_u: string, init?: RequestInit) => {
    sent = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({ closures: [{ id: "md-1", from_m: 1, to_m: 2, text: "x" }], unchecked: null }), { status: 200 });
  }) as unknown as typeof fetch;
  const found = await checkClosures("https://x.test", LINE, ok);
  assert.equal(found?.closures.length, 1);
  assert.equal((sent as { line: unknown[] }).line.length, LINE.length);
  const offline = (async () => {
    throw new Error("offline");
  }) as unknown as typeof fetch;
  assert.equal(await checkClosures("https://x.test", LINE, offline), null);
});

test("Save route sits beside Share in Plan's and Go's route sheet, and My routes in Plan's menu and Go's More", () => {
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /SAVE_ROUTE/);
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  assert.match(sheets, /<MyRoutes /);
});

test("F15. Go's route chips stay one row at 390 px: Save shown short, the ride type's name cut short, never the actions", () => {
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  const panel = read("../app/RoutePanel.tsx");
  const chips = panel.slice(panel.indexOf('<div className="go-chips"'), panel.indexOf("{/* The elevation chart"));
  assert.match(chips, /<SaveRoute \{\.\.\.actions\.save\} label=\{SAVE_ROUTE\} shown=\{SAVE_SHORT\} chip \/>/);
  // Named "Save route", shown "Save": the words shown are in the name.
  const save = read("../SaveRoute.tsx");
  assert.match(save, /aria-label=\{shown \? label : undefined\}/);
  assert.match(save, /\{shown \?\? label\}/);
  // Only the ride type keeps an icon (four icons and their padding were what made the row wrap).
  assert.equal((chips.match(/<Icon /g) ?? []).length, 1, "the ride type's bike");
  assert.match(save, /\{chip && !shown && <Icon name="download" size=\{18\} \/>\}/);
  assert.match(chips, /<span className="go-chip-name">\s*<PresetName id=\{preset\} \/>\s*<\/span>/);
  const css = read("../styles.css");
  assert.match(css, /\.go-chips > \.go-ride-chip \{\s*flex: 1 1 0;\s*min-width: 0;\s*max-width: max-content;/);
  assert.match(css, /\.go-chip-name \{[^}]*text-overflow: ellipsis;/);
  // Save's form and its line take lines of their own under the row.
  assert.match(css, /\.go-chips \.save-route-form,\s*\.go-chips \.save-route-said \{\s*flex: 1 0 100%;/);
  // An estimate at Go's chip size (0.95rem, about 8.5 px a character; 10 px padding and a 1 px border each side;
  // the bike icon 18 px and its 6 px gap): "3 routes", "Plan", "Save" and three 6 px gaps leave the ride type 142 of
  // the 362 px a 390 px phone's sheet holds, so Default, Bikeshare and Cargo Bike show whole; longer names end "…".
  const chip = (text: string, icon: boolean) => 22 + text.length * 8.5 + (icon ? 24 : 0);
  const left = 362 - (chip("3 routes", false) + chip("Plan", false) + chip("Save", false) + 3 * 6);
  for (const name of ["Default", "Bikeshare", "Cargo Bike"]) assert.ok(chip(name, true) <= left, `${name}: ${chip(name, true)} of ${left} px`);
});
