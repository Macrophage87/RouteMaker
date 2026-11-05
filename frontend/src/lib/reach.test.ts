// Reach (Stephen, 2026-11-04): the request's body, the words, the map's features and the shareable link.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { startDials } from "./dials.ts";
import {
  REACH_DEFAULT,
  REACH_MAX_POINTS,
  reachBody,
  reachFeatures,
  reachFromHash,
  reachHashParam,
  reachNotes,
  reachOffered,
  reachPointNames,
  reachShareLink,
  reachSentence,
  requestReach,
  shareCancelled,
  sharesHome,
  toggleMinutes,
  withReach,
  type ReachAnswer,
} from "./reach.ts";
import type { LonLat } from "./geo.ts";
import { loadLanguage, setLanguageForTest } from "./i18n.ts";

const HERE: LonLat = [-77.05, 38.9];
const SQUARE = { type: "Polygon" as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };

function ring(minutes: number, sqMi: number, metro: number) {
  return { minutes, geometry: SQUARE, area_sq_mi: sqMi, area_km2: sqMi * 2.59, places: { metro, racks: 10, food: 20, sights: 3 } };
}

const ANSWER: ReachAnswer = {
  preset: "default",
  minutes: [15, 30, 45, 60],
  direction: "from",
  combine: "any",
  stress_used: 70,
  groups: [{ point: null, rings: [ring(15, 2, 1), ring(30, 14, 3), ring(45, 30, 6), ring(60, 50, 9)], metro_stations: ["Dupont Circle"] }],
  calm: { stress: 80, groups: [{ point: null, rings: [ring(15, 1, 0), ring(30, 9.2, 1), ring(45, 20, 2), ring(60, 33, 4)], metro_stations: [] }] },
  unplaced: [],
};

test("the body carries the plan's points, ride type and dials, and the view", () => {
  const body = reachBody([HERE], "fast", startDials("fast"), REACH_DEFAULT);
  assert.deepEqual(body.points, [HERE]);
  assert.equal(body.preset, "fast");
  assert.equal(body.stress, startDials("fast").stress);
  assert.equal(body.direction, "from");
  assert.equal(body.calm, true);
  // One point: nothing to combine.
  assert.equal(body.combine, "any");
  for (const field of ["loop", "target_distance_m", "system_weight_kg", "ride_size"]) assert.equal(body[field], undefined, field);
});

test("several points: at most five, combined as chosen; Mass Ride's size is not sent", () => {
  const many: LonLat[] = Array.from({ length: 7 }, (_, i) => [-77 - i * 0.01, 38.9]);
  const body = reachBody(many, "mass-ride", { ...startDials("mass-ride"), rideSize: 800 }, { ...REACH_DEFAULT, combine: "all" });
  assert.equal((body.points as LonLat[]).length, REACH_MAX_POINTS);
  assert.equal(body.combine, "all");
  assert.equal(body.ride_size, undefined);
  // Side by side: one colour a point, no calm layer asked for.
  assert.equal(reachBody(many, "default", startDials("default"), { ...REACH_DEFAULT, combine: "each" }).calm, false);
  assert.equal(reachBody([HERE], "default", startDials("default"), { ...REACH_DEFAULT, combine: "each" }).calm, true);
});

test("Run sends its pace; other ride types do not", () => {
  assert.equal(reachBody([HERE], "run", startDials("run"), REACH_DEFAULT, 9.7).run_pace_kmh, 9.7);
  assert.equal(reachBody([HERE], "default", startDials("default"), REACH_DEFAULT, 9.7).run_pace_kmh, undefined);
});

test("the transit ride types have no rings yet", () => {
  assert.equal(reachOffered("bike-transit"), false);
  assert.equal(reachOffered("walk-transit"), false);
  assert.equal(reachOffered("mass-ride"), true);
  assert.equal(reachOffered("walk"), true);
});

test("the answer in one sentence: the 30 minute ring, and the calm one beside it", () => {
  const said = reachSentence(ANSWER, 1);
  assert.match(said, /^From here, 30 min reaches 14 sq mi/);
  assert.match(said, /3 Metro stations/);
  assert.match(said, /On Low-stress streets: 9\.2 sq mi/);
  assert.match(reachSentence({ ...ANSWER, direction: "to" }, 1), /^To here, 30 min comes from/);
  assert.match(reachSentence({ ...ANSWER, combine: "all" }, 3), /^From every point/);
});

test("notes: rings held at Low-stress, points left out", () => {
  assert.equal(reachNotes(ANSWER, 70, 1).length, 0);
  assert.equal(reachNotes({ ...ANSWER, stress_used: 80 }, 100, 1).length, 1);
  assert.match(reachNotes({ ...ANSWER, unplaced: [1] }, 70, 2)[0], /1 point is off/);
});

test("map features: largest first, the calm ones marked", () => {
  const { features } = reachFeatures(ANSWER);
  assert.equal(features.length, 8);
  assert.deepEqual(features.slice(0, 4).map((f) => f.properties.minutes), [60, 45, 30, 15]);
  assert.ok(features.slice(4).every((f) => f.properties.calm));
});

test("the link: reach= added to the plan's fragment, read back, replaced not repeated", () => {
  const view = { direction: "to" as const, combine: "each" as const, calm: false, minutes: [15, 30, 45, 60] };
  assert.equal(reachHashParam(view), "reach=to.each");
  const hash = withReach("#v=2&q=abc&preset=fast", view);
  assert.equal(hash, "#v=2&q=abc&preset=fast&reach=to.each");
  assert.deepEqual(reachFromHash(hash), view);
  assert.equal(withReach(hash, REACH_DEFAULT), "#v=2&q=abc&preset=fast&reach=from.any.calm");
  assert.equal(reachFromHash("#v=2&q=abc"), null);
});

test("a point near Home is said before sharing", () => {
  assert.equal(sharesHome([HERE], [-77.0502, 38.9001]), true);
  assert.equal(sharesHome([HERE], [-77.1, 38.9]), false);
  assert.equal(sharesHome([HERE], null), false);
});

test("a refusal is a sentence to say", async () => {
  const busy = await requestReach({}, async () => new Response(JSON.stringify({ error: "x" }), { status: 503 }));
  assert.ok(!busy.ok && /busy/.test(busy.message));
  const refused = await requestReach({}, async () => new Response(JSON.stringify({ error: "None of the points is on a street" }), { status: 422 }));
  assert.ok(!refused.ok && /None of the points/.test(refused.message));
  const lost = await requestReach({}, async () => {
    throw new TypeError("offline");
  });
  assert.ok(!lost.ok && /connection/.test(lost.message));
  const fine = await requestReach({}, async () => new Response(JSON.stringify(ANSWER), { status: 200 }));
  assert.ok(fine.ok);
});

test("only some rings: sent, kept in the link, and never none", () => {
  const view = { ...REACH_DEFAULT, minutes: [15, 45] };
  assert.deepEqual(reachBody([HERE], "default", startDials("default"), view).minutes, [15, 45]);
  assert.deepEqual(reachBody([HERE], "default", startDials("default"), REACH_DEFAULT).minutes, [15, 30, 45, 60]);
  assert.equal(withReach("#v=2", view), "#v=2&reach=from.any.calm.15.45");
  assert.deepEqual(reachFromHash("#reach=from.any.calm.15.45")?.minutes, [15, 45]);
  // An older link, with no minutes named, opens all four.
  assert.deepEqual(reachFromHash("#reach=from.any")?.minutes, [15, 30, 45, 60]);
  assert.deepEqual(toggleMinutes([15, 45], 30), [15, 30, 45]);
  assert.deepEqual(toggleMinutes([15, 45], 15), [45]);
  assert.deepEqual(toggleMinutes([45], 45), [45]);
});

test("a shared ring link never carries the Group or Mass Ride secret", () => {
  const where = { origin: "https://example.org", pathname: "/", search: "", hash: "#p=-77.03,38.9&k=s3cr3tKEY&ride=1" };
  const link = reachShareLink(where, REACH_DEFAULT);
  assert.ok(!link.includes("k=s3cr3tKEY"), link);
  assert.ok(link.includes("p=-77.03,38.9") && link.includes("reach=from.any.calm"), link);
});

test("Side by side names each point's rings as its marker on the map is named: Start, Stop 1, End; a loop's start is its start and finish", () => {
  const points: LonLat[] = [HERE, [-77.04, 38.91], [-77.03, 38.92]];
  assert.deepEqual(reachPointNames(points, false, () => false), ["Start", "Stop 1", "End"]);
  assert.deepEqual(reachPointNames(points, true, () => false), ["Start and finish", "Stop 1", "Stop 2"]);
  assert.deepEqual(reachPointNames(points, false, (p) => p === points[1]), ["Start", "Via point", "End"]);
  const sheet = readFileSync(new URL("../ReachSheet.tsx", import.meta.url), "utf8");
  // The list's group headings use these names, with the group's colour beside them.
  assert.match(sheet, /names\[group\.point \?\? g\]/);
  assert.match(sheet, /className="reach-key" aria-hidden="true" style=\{\{ background: REACH_COLOURS\[\(group\.point \?\? g\) % REACH_COLOURS\.length\] \}\}/);
});

test("Share these rings: the share sheet closed by the rider copies nothing; refused or missing, the link is copied", () => {
  assert.equal(shareCancelled(new DOMException("closed", "AbortError")), true);
  assert.equal(shareCancelled(new DOMException("no", "NotAllowedError")), false);
  assert.equal(shareCancelled(new TypeError("x")), false);
  const sheet = readFileSync(new URL("../ReachSheet.tsx", import.meta.url), "utf8");
  assert.match(sheet, /catch \(error\) \{[^}]*if \(shareCancelled\(error\)\) return;/);
});

test("rings that come before the map has loaded are drawn once it has (a shared Reach link on a slow phone)", () => {
  const sheet = readFileSync(new URL("../ReachSheet.tsx", import.meta.url), "utf8");
  assert.match(sheet, /\}, \[open, answer, getMap, pointsKey, mapReady\]\);/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /mapRef\.current = map;\s*setMapReady\(true\);/);
  assert.match(app, /mapReady=\{mapReady\}/);
});

test("Reach's refusals are in the page's language: the server's English is never shown on a Spanish page", async () => {
  await loadLanguage("es");
  setLanguageForTest("es");
  try {
    const refused = await requestReach({}, async () => new Response(JSON.stringify({ error: "None of the points is on a street" }), { status: 422 }));
    assert.ok(!refused.ok && /^Ninguno de los puntos/.test(refused.message), refused.ok ? "" : refused.message);
    const router = await requestReach({}, async () => new Response(JSON.stringify({ error: "The router could not draw these rings." }), { status: 502 }));
    assert.ok(!router.ok && /^El enrutador no pudo/.test(router.message));
    const other = await requestReach({}, async () => new Response(JSON.stringify({ error: "points: some English" }), { status: 400 }));
    assert.ok(!other.ok && !/English/.test(other.message));
  } finally {
    setLanguageForTest("en");
  }
});

test("Reach's empty state says how to put a point from the sheet, and the greyed Share says why", () => {
  const sheet = readFileSync(new URL("../ReachSheet.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(sheet, /search for a place or tap the map/);
  assert.match(sheet, /t\("Tap the map to put a point, or go back to the planner to search for a place\./);
  assert.match(sheet, /disabled=\{!answer\} aria-describedby=\{answer \? undefined : "reach-share-hint"\}/);
});

test("Reach's low-stress layer is named as the slider names it, and the note never says 'above Low-stress'", () => {
  const answer = { ...ANSWER, stress_used: 80 };
  const [note] = reachNotes(answer, 100, 1);
  assert.match(note, /^At Calm and Calmest, the rings are drawn at Low-stress/);
  assert.doesNotMatch(note, /Above Low-stress|Low-stress's/);
  const sheet = readFileSync(new URL("../ReachSheet.tsx", import.meta.url), "utf8");
  assert.match(sheet, /t\("Low-stress streets"\)/);
  assert.doesNotMatch(sheet, /t\("Calm streets"\)/);
});

test("Reach is named in the page's language (Spanish covers Plan): its chip and heading", async () => {
  const sidebar = readFileSync(new URL("./sidebar.ts", import.meta.url), "utf8");
  assert.match(sidebar, /reach: t\("Reach"\),/);
  const { ES } = await import("../i18n/es.ts");
  assert.equal(ES.Reach, "Alcance");
});
