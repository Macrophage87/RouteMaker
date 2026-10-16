// Trail mile markers (OWNER-DECISIONS 465; Stephen, 2026-10-16): the file, the nearest posted marker or the
// computed mile, the words for the 311 report, "Where am I?" and the road panel, and the map's layers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import {
  LINE_NEAR_M,
  MARKER_FAR_M,
  MARKER_NEAR_M,
  MILE_MIN_ZOOM,
  MILES_LAYER,
  loadTrailMiles,
  mileFigure,
  milePanelRow,
  milePanelValue,
  milesCard,
  milesGeoJson,
  milesLabelLayer,
  milesLayer,
  mileWords,
  parseTrailMiles,
  projectOnLine,
  trailKey,
  trailMileAt,
} from "./trailMiles.ts";

const M_PER_DEG = 111_195;
const LON = -77.1;
const north = (m: number, east = 0): LonLat => [LON + east / (M_PER_DEG * Math.cos((38.9 * Math.PI) / 180)), 38.9 + m / M_PER_DEG];

/** The Capital Crescent Trail, 4 km north from its mile 0, with posts at miles 1 and 2. */
function file() {
  return {
    source: "OpenStreetMap contributors, ODbL 1.0",
    trails: [{ n: "Capital Crescent Trail", s: 0, l: [north(0), north(2000), north(4000)] }],
    markers: [
      { id: "n1", x: north(1609)[0], y: north(1609)[1], t: "Capital Crescent Trail", m: 1 },
      { id: "n2", x: north(3219)[0], y: north(3219)[1], t: "Capital Crescent Trail", m: 2 },
    ],
  };
}

test("the file: markers and lines, the lines measured; bad rows dropped; the wrong shape is null", () => {
  const data = parseTrailMiles(file())!;
  assert.equal(data.markers.length, 2);
  assert.equal(data.lines.length, 1);
  assert.equal(data.markers[0].key, "capital crescent trail", "the name to match on, worked out once");
  assert.equal(data.lines[0].key, "capital crescent trail");
  assert.ok(Math.abs(data.lines[0].along[2] - 4000) < 1, `${data.lines[0].along[2]}`);
  const messy = parseTrailMiles({
    trails: [{ n: "One point", l: [north(0)] }, { n: " ", l: [north(0), north(10)] }, { n: "Kept", l: [north(0), north(10)] }],
    markers: [{ id: "n3", x: LON, y: 38.9, t: "X", m: -1 }, { id: "n4", x: "a", y: 38.9, t: "X", m: 1 }, { id: "n5", x: LON, y: 38.9, t: "X", m: 1.5 }],
  })!;
  assert.deepEqual(messy.lines.map((l) => [l.trail, l.startM]), [["Kept", 0]]);
  assert.deepEqual(messy.markers.map((m) => m.id), ["n5"]);
  assert.equal(parseTrailMiles({ points: [] }), null);
  assert.equal(parseTrailMiles(null), null);
});

test("the bundled file parses (empty until scripts/build_trail_miles.py fills it)", () => {
  const raw = JSON.parse(readFileSync(new URL("../amenity-data/trail-miles.json", import.meta.url), "utf8"));
  assert.ok(parseTrailMiles(raw));
  assert.equal(raw.source, "OpenStreetMap contributors, ODbL 1.0");
});

test("loadTrailMiles: the file, or null when it cannot be had", async () => {
  const ok = await loadTrailMiles("/x", async () => ({ ok: true, json: async () => file() }));
  assert.equal(ok?.markers.length, 2);
  assert.equal(await loadTrailMiles("/x", async () => ({ ok: false, json: async () => ({}) })), null);
  assert.equal(await loadTrailMiles("/x", async () => { throw new Error("offline"); }), null);
});

test("a trail is matched by name, case, & and punctuation aside", () => {
  assert.equal(trailKey("C&O Canal Towpath"), trailKey("C and O canal towpath"));
  assert.equal(trailKey("Washington & Old Dominion Railroad Regional Park"), "washington and old dominion railroad regional park");
  assert.equal(trailKey("Mount Vernon Trail"), trailKey("Mount  Vernon Trail."));
});

test("projectOnLine: metres off the line and along it", () => {
  const data = parseTrailMiles(file())!;
  const at = projectOnLine(data.lines[0].line, data.lines[0].along, north(2500, 30));
  assert.ok(Math.abs(at.offM - 30) < 1, `${at.offM}`);
  assert.ok(Math.abs(at.alongM - 2500) < 1, `${at.alongM}`);
});

test("trailMileAt: the post within 500 ft, else the computed mile, else a post within half a mile, else nothing", () => {
  const data = parseTrailMiles(file())!;
  assert.ok(Math.abs(MARKER_NEAR_M * 3.28084 - 500) < 0.01, "500 ft");
  const atPost = trailMileAt(data, "Capital Crescent Trail", north(1650));
  assert.deepEqual(atPost && { ...atPost, metres: Math.round(atPost.metres) }, { kind: "marker", trail: "Capital Crescent Trail", mile: 1, metres: 41 });
  assert.deepEqual(trailMileAt(data, "capital crescent trail", north(2400)), { kind: "computed", trail: "Capital Crescent Trail", mile: 1.5 });
  // The line's start is set by the posts (s): mile 0 half a mile before the line's first point.
  const shifted = parseTrailMiles({ ...file(), trails: [{ ...file().trails[0], s: 805 }] })!;
  assert.deepEqual(trailMileAt(shifted, "Capital Crescent Trail", north(2400)), { kind: "computed", trail: "Capital Crescent Trail", mile: 2 });
  // Off the line (a parallel road, a branch): not on the trail; another trail's name: nothing.
  assert.equal(trailMileAt(data, "Capital Crescent Trail", north(2414, LINE_NEAR_M + 20)), null);
  assert.equal(trailMileAt(data, "River Road", north(2400)), null);
  assert.equal(trailMileAt(null, "Capital Crescent Trail", north(2400)), null);
  assert.equal(trailMileAt(data, null, north(2400)), null);
  // No line, a post 0.3 mi off: named as near it; beyond half a mile, nothing.
  const postsOnly = parseTrailMiles({ ...file(), trails: [] })!;
  const nearish = trailMileAt(postsOnly, "Capital Crescent Trail", north(1609 + 480));
  assert.equal(nearish?.kind === "marker" && nearish.mile, 1);
  assert.equal(trailMileAt(postsOnly, "Capital Crescent Trail", north(1609 - MARKER_FAR_M - 50)), null);
  // Never below mile 0.
  const behind = parseTrailMiles({ ...file(), trails: [{ ...file().trails[0], s: -2000 }] })!;
  assert.deepEqual(trailMileAt(behind, "Capital Crescent Trail", north(500)), { kind: "computed", trail: "Capital Crescent Trail", mile: 0 });
});

test("the words: a post as it says it, a computed mile as about; the panel with US units first", () => {
  assert.equal(mileFigure(3), "3");
  assert.equal(mileFigure(3.5), "3.5");
  assert.equal(mileWords({ kind: "marker", trail: "T", mile: 3, metres: 40 }), "mile marker 3");
  assert.equal(mileWords({ kind: "marker", trail: "T", mile: 3, metres: 600 }), "near mile marker 3");
  assert.equal(mileWords({ kind: "computed", trail: "T", mile: 3 }), "about mile 3.0");
  assert.equal(mileWords({ kind: "computed", trail: "T", mile: 3.2 }), "about mile 3.2");
  assert.equal(milePanelValue({ kind: "marker", trail: "T", mile: 3, metres: 91 }), "Mile marker 3, 300 ft (91 m) away");
  assert.equal(milePanelValue({ kind: "computed", trail: "T", mile: 3.2 }), "About mile 3.2 here");
  const data = parseTrailMiles(file())!;
  assert.deepEqual(milePanelRow(data, "Capital Crescent Trail", north(2400)), { id: "trail-mile", label: "Trail mile", value: "About mile 1.5 here" });
  assert.equal(milePanelRow(data, "Unnamed road", north(2400)), null);
});

test("the map: posts from the trail zooms in, the figure beside each in text, a tap card in words", () => {
  const data = parseTrailMiles(file())!;
  const geo = milesGeoJson(data.markers) as { features: Array<{ properties: { id: string; label: string } }> };
  assert.deepEqual(geo.features.map((f) => f.properties), [{ id: "n1", label: "1" }, { id: "n2", label: "2" }]);
  assert.equal(MILE_MIN_ZOOM, 14);
  assert.equal(milesLayer().id, MILES_LAYER);
  assert.equal(milesLayer().minzoom, MILE_MIN_ZOOM);
  const label = milesLabelLayer() as { minzoom: number; layout: Record<string, unknown> };
  assert.equal(label.minzoom, MILE_MIN_ZOOM);
  assert.deepEqual(label.layout["text-field"], ["concat", "MM ", ["get", "label"]]);
  assert.deepEqual(milesCard(data.markers[1]), ["Capital Crescent Trail", "Mile marker 2.", "From OpenStreetMap."]);
});

test("worked out on the device: the mile code fetches only its own file, never with a position", () => {
  const source = readFileSync(new URL("./trailMiles.ts", import.meta.url), "utf8");
  assert.equal(source.match(/fetch\(/g)?.length, 1);
  assert.match(source, /\(u\) => fetch\(u\)/);
});
