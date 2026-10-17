// Review, the third view (lib/review.ts, lib/appMode.ts; the owner, 2026-10-16: "Basically we'd have 3 modes for
// people who have admin access go/plan/review").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { MODE_LABEL, isMode, isOpenIn, modeSaid, readLastReview, reopenReview, switchModes, writeLastReview } from "./appMode.ts";
import {
  DEFAULT_LIST,
  LISTS,
  QUEUES,
  QUEUE_STYLE,
  decisionLabel,
  fetchMapView,
  fetchNext,
  fetchRoadDetail,
  fetchRoads,
  makeAnnouncer,
  piecesText,
  progressText,
  roadHeading,
  roadRowLabel,
  roadStreetViewUrl,
  ruledSaid,
  rulingLabel,
  sendRuling,
  sortRoads,
  stepText,
  trafficText,
  drawnOf,
  maxViewWidth,
  typingIn,
  viewBox,
  viewZoom,
  type ReviewRoad,
} from "./review.ts";

function road(way: number, change: Partial<ReviewRoad> = {}): ReviewRoad {
  return {
    queue: "rebuild",
    osm_way_id: way,
    name: "",
    area: "",
    reason: "",
    kind: "4-2",
    kind_label: "LTS 4 to LTS 2",
    old_step: 4,
    new_step: 2,
    old_words: null,
    new_words: "",
    old_closed: false,
    new_closed: false,
    old_rule: null,
    new_rule: null,
    old_source: null,
    new_source: null,
    sources: [],
    ratings: [],
    spread: null,
    length_m: 100,
    length: "0.06 mi (0.10 km)",
    ways: [way],
    pieces: 1,
    aadt: null,
    bbox: null,
    geometry: null,
    point: null,
    actions: ["accept", "reject", "set"],
    ruling: null,
    ...change,
  };
}

test("Review is offered only to someone who may review, and is never one of My Go's Open in choices", () => {
  assert.deepEqual(switchModes(false), ["go", "plan"]);
  assert.deepEqual(switchModes(true), ["go", "plan", "review"]);
  assert.equal(MODE_LABEL.review, "Review");
  assert.ok(isMode("review"));
  assert.equal(isOpenIn("review"), false);
  assert.match(modeSaid("review"), /^Review: /);
});

test("the device remembers Review, and it comes back only where nothing else chose the view", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), removeItem: (k: string) => void kept.delete(k) };
  writeLastReview(true, store);
  assert.equal(readLastReview(store), true);
  const base = { lastReview: true, canReview: true, by: "screen" as const, switched: false, mode: "plan" as const };
  assert.equal(reopenReview(base), true);
  assert.equal(reopenReview({ ...base, canReview: false }), false);
  assert.equal(reopenReview({ ...base, by: "link" }), false);
  assert.equal(reopenReview({ ...base, by: "tab" }), false);
  assert.equal(reopenReview({ ...base, switched: true }), false);
  writeLastReview(false, store);
  assert.equal(readLastReview(store), false);
});

test("the lists, Rebuild changes first, and the ruling buttons' names", () => {
  assert.equal(DEFAULT_LIST, "rebuild");
  assert.equal(LISTS[0].key, "rebuild");
  assert.ok(LISTS.some((l) => l.key === "suggestions") && LISTS.some((l) => l.key === "closures"));
  assert.equal(decisionLabel("rebuild", "accept"), "Keep new");
  assert.equal(decisionLabel("rebuild", "reject"), "Keep old");
  assert.equal(decisionLabel("rebuild", "set"), "Set LTS");
  assert.equal(decisionLabel("works_closure", "reject"), "Reopen");
  assert.equal(decisionLabel("disagreement", "accept"), "Keep current");
  // A road's own buttons name the level each keeps; the batch's keep the bare words.
  const rebuild = { queue: "rebuild" as const, old_step: 2, old_closed: false, new_step: 4, new_closed: false };
  assert.equal(rulingLabel(rebuild, "reject"), "Keep old: LTS 2");
  assert.equal(rulingLabel(rebuild, "accept"), "Keep new: LTS 4");
  assert.equal(rulingLabel({ ...rebuild, new_step: 5 }, "accept"), "Keep new: Avoid");
  assert.equal(rulingLabel({ ...rebuild, new_closed: true }, "accept"), "Keep new: Closed");
  assert.equal(rulingLabel({ ...rebuild, old_step: null }, "reject"), "Keep old");
  assert.equal(rulingLabel(rebuild, "set"), "Set LTS");
  assert.equal(rulingLabel({ ...rebuild, queue: "works_closure" }, "reject"), "Reopen");
});

test("Street View at the road's own point, as the road panel links it", () => {
  assert.equal(roadStreetViewUrl({ point: [-77.1, 39.05] }), "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=39.050000,-77.100000");
  assert.equal(roadStreetViewUrl({ point: null }), null);
  assert.equal(roadStreetViewUrl({ point: [Number.NaN, 39] }), null);
});

test("words: levels, progress, traffic, a road's heading and what a ruling says", () => {
  assert.equal(stepText(2.5), "LTS 2.5");
  assert.equal(stepText(5), "Avoid");
  assert.equal(stepText(3, true), "Closed");
  assert.equal(progressText(12, 601), "12 of 601 reviewed");
  assert.equal(progressText(1200, 3400), "1,200 of 3,400 reviewed");
  assert.equal(trafficText(18400), "18,400 a day");
  assert.equal(trafficText(null), "No count");
  assert.equal(roadHeading({ name: "Oak Street", osm_way_id: 1, area: "Montgomery County", kind_label: "LTS 4 to LTS 2" }), "Oak Street, Montgomery County: LTS 4 to LTS 2");
  assert.equal(roadHeading({ name: "", osm_way_id: 7, area: "", kind_label: "Newly closed to bicycles" }), "Unnamed way 7: Newly closed to bicycles");
  assert.equal(ruledSaid({ name: "Oak Street", osm_way_id: 1 }, { summary: "Kept LTS 4" }, "Elm Street"), "Oak Street: Kept LTS 4. Next: Elm Street.");
  assert.equal(ruledSaid({ name: "", osm_way_id: 1 }, { summary: "Accepted" }, null), "Way 1: Accepted. No more roads in this list.");
});

test("the table sorts by a column, and by the server's order by default", () => {
  const roads = [road(1, { name: "Elm", length_m: 50, aadt: 900 }), road(2, { name: "ash", length_m: 300 }), road(3, { name: "Birch", length_m: 10, aadt: 20000 })];
  assert.deepEqual(sortRoads(roads, "score", false).map((r) => r.osm_way_id), [1, 2, 3]);
  assert.deepEqual(sortRoads(roads, "name", true).map((r) => r.osm_way_id), [2, 3, 1]);
  assert.deepEqual(sortRoads(roads, "length", false).map((r) => r.osm_way_id), [2, 1, 3]);
  assert.deepEqual(sortRoads(roads, "traffic", false).map((r) => r.osm_way_id), [3, 1, 2]);
});

test("the requests: a list's open roads with its filters, and a ruling with no reason of its own", async () => {
  const asked: { url: string; init: RequestInit }[] = [];
  const run = (async (url: string, init: RequestInit) => {
    asked.push({ url, init });
    return new Response(JSON.stringify({ queue: "rebuild", build_id: "b", page: 1, per_page: 50, total: 0, items: [], rulings: [], refused: [], generation: null, message: "1 road ruled." }), { status: 200 });
  }) as typeof fetch;
  await fetchRoads("https://x", "rebuild", { kind: "4-2", source: "", area: "Montgomery County" }, {}, run);
  const url = new URL(asked[0].url);
  assert.equal(url.pathname, "/api/review/items");
  assert.equal(url.searchParams.get("kind"), "4-2");
  assert.equal(url.searchParams.get("area"), "Montgomery County");
  assert.equal(url.searchParams.get("open_only"), "true");
  assert.equal(url.searchParams.has("source"), false);
  const sent = await sendRuling("https://x", { queue: "disagreement", osm_way_ids: [5], decision: "set", step: 2 }, "token", run);
  assert.ok(sent.ok);
  const body = JSON.parse(String(asked[1].init.body));
  assert.deepEqual(body, { queue: "disagreement", osm_way_ids: [5], decision: "set", step: 2 });
  assert.equal((asked[1].init.headers as Record<string, string>)["X-CSRFToken"], "token");
});

const src = (file: string) => readFileSync(new URL(`../${file}`, import.meta.url), "utf8");

test("Next discrepancy and Previous and Next road ask the server for the road after, in the lists' order", async () => {
  const asked: string[] = [];
  const answers = [{ next: { queue: "disagreement", osm_way_id: 11 } }, { next: null }];
  const run = (async (url: string) => {
    asked.push(url);
    return new Response(JSON.stringify(answers.shift()), { status: 200 });
  }) as typeof fetch;
  assert.deepEqual(await fetchNext("https://x", { lists: ["rebuild", "disagreement"], queue: "rebuild", way: 3 }, run), { queue: "disagreement", way: 11 });
  assert.equal(await fetchNext("https://x", { lists: ["rebuild"], queue: "rebuild", way: 3, direction: -1, openOnly: false, wrap: false }, run), null);
  assert.deepEqual(asked, [
    "https://x/api/review/next?lists=rebuild%2Cdisagreement&queue=rebuild&way=3&direction=1&open_only=true&wrap=true",
    "https://x/api/review/next?lists=rebuild&queue=rebuild&way=3&direction=-1&open_only=false&wrap=false",
  ]);
});

test("Alt+Shift+N is left to a text box, a text area and an editable region", () => {
  assert.ok(typingIn({ tagName: "INPUT", type: "text" }));
  assert.ok(typingIn({ tagName: "INPUT" }));
  assert.ok(typingIn({ tagName: "INPUT", type: "search" }));
  assert.ok(typingIn({ tagName: "TEXTAREA" }));
  assert.ok(typingIn({ tagName: "DIV", isContentEditable: true }));
  assert.ok(!typingIn({ tagName: "INPUT", type: "checkbox" }));
  assert.ok(!typingIn({ tagName: "BUTTON" }));
  assert.ok(!typingIn(null));
  const view = src("ReviewMode.tsx");
  assert.match(view, /if \(typingIn\(event\.target\)\) return;/);
});

test("what is said within a moment is said together, never one message over another", () => {
  const sent: string[] = [];
  const timers: (() => void)[] = [];
  const say = makeAnnouncer((text) => sent.push(text), 80, (run) => timers.push(run));
  say("Rebuild changes: 3 of 10 reviewed.");
  say("Oak Street: LTS 4 to LTS 2.");
  say("Oak Street: LTS 4 to LTS 2.");
  assert.equal(timers.length, 1);
  timers[0]();
  assert.deepEqual(sent, ["Rebuild changes: 3 of 10 reviewed. Oak Street: LTS 4 to LTS 2."]);
  say("Undone.");
  timers[1]();
  assert.deepEqual(sent.at(-1), "Undone.");
});

test("each list's map style is its own colour and its own line, from the colour-blind-safe palette", () => {
  const okabeIto = new Set(["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#000000"]);
  const colours = QUEUES.map((q) => QUEUE_STYLE[q].colour);
  assert.equal(new Set(colours).size, QUEUES.length);
  assert.ok(colours.every((c) => okabeIto.has(c)));
  // The two solid lines are the palette's most distinct pair; every other list is told by its dashes as well.
  const patterns = QUEUES.map((q) => `${QUEUE_STYLE[q].colourName} ${QUEUE_STYLE[q].pattern}`);
  assert.equal(new Set(patterns).size, QUEUES.length);
});

test("the map is asked for the view alone, at its zoom, and the road's facts with the new build's for a rebuild", async () => {
  const asked: string[] = [];
  const run = (async (url: string) => {
    asked.push(url);
    return new Response(JSON.stringify({ lines: { type: "FeatureCollection", features: [] } }), { status: 200 });
  }) as typeof fetch;
  await fetchMapView("https://x", ["rebuild", "disagreement"], [-77.2, 38.8, -76.9, 39], 11.234, run);
  await fetchRoadDetail("https://x", 5, "rebuild", run);
  await fetchRoadDetail("https://x", 6, null, run);
  assert.deepEqual(asked, [
    "https://x/api/review/map?queues=rebuild%2Cdisagreement&west=-77.2&south=38.8&east=-76.9&north=39&zoom=11.2",
    "https://x/api/review/road/5?queue=rebuild",
    "https://x/api/review/road/6",
  ]);
  // Inside the world's bounds, whatever the map's view; a view across the date line is the whole width.
  assert.deepEqual(viewBox(-77.123456, 38.8, -76.9, 39), [-77.12346, 38.8, -76.9, 39]);
  assert.deepEqual(viewBox(-400, -95, 400, 95), [-180, -90, 180, 90]);
  assert.deepEqual(viewBox(170, 0, 190, 10), [170, 0, 180, 10]);
  assert.deepEqual(viewBox(-200, 0, -170, 10), [-180, 0, -170, 10]);
  // Never wider than the server draws at the zoom sent (to a tenth, rounded down): narrowed about its middle.
  assert.equal(viewZoom(11.29), 11.2);
  const [w, s, e, n] = viewBox(-80, 38, -74, 40, 11.29);
  assert.ok(e - w <= maxViewWidth(11.2) && e - w > maxViewWidth(11.2) - 0.001, `${e - w}`);
  assert.ok(Math.abs((w + e) / 2 + 77) < 1e-4 && s === 38 && n === 40);
  // South never past north.
  assert.deepEqual(viewBox(-77, 39, -76.9, 38.9, 12), [-77, 38.9, -76.9, 39]);
});

test("a list switched off leaves the map at once, its badges with it, before (or without) a new answer", () => {
  const line = (way: number, queue: "rebuild" | "disagreement") => ({ type: "Feature" as const, geometry: null, properties: { way, queue, ruled: false } });
  const fc = <T,>(features: T[]) => ({ type: "FeatureCollection" as const, features });
  const view = { zoom: 9, detail: "low" as const, truncated: false, lines: fc([line(1, "rebuild"), line(2, "disagreement")]), dots: fc([line(1, "rebuild")]), badges: fc([{ type: "Feature" as const, geometry: null, properties: { count: 5 } }]) };
  const both = drawnOf(view, ["rebuild", "disagreement"], ["rebuild", "disagreement"]);
  assert.equal(both?.lines.features.length, 2);
  assert.equal(both?.badges.features.length, 1);
  const one = drawnOf(view, ["rebuild", "disagreement"], ["disagreement"]);
  assert.deepEqual(one?.lines.features.map((f) => f.properties.way), [2]);
  assert.equal(one?.dots.features.length, 0);
  assert.equal(one?.badges.features.length, 0);
  assert.equal(drawnOf(null, [], []), null);
  const page = src("ReviewMode.tsx");
  // A newer view cancels the request before it; a slower Next answer never opens after a newer one.
  assert.match(page, /controller\.abort\(\);/);
  assert.match(page, /if \(asking !== nextAsked\.current\) return;/);
  assert.match(page, /if \(asking !== besideAsked\.current\) return;/);
});

test("Review's map asks for the view's roads as it moves, with count badges far out and a dot a road", () => {
  const view = src("ReviewMode.tsx");
  // Never a list's whole map: the view, on a settled move, for the lists switched on.
  assert.match(view, /fetchMapView\(origin, lists, viewBox\(/);
  assert.match(view, /map\.on\("moveend", onMove\)/);
  assert.doesNotMatch(view, /cluster: true|fetchMap\(/);
  // The badges are the server's counts, and zoom in when chosen.
  assert.match(view, /id: BADGES,\s*type: "circle"/);
  assert.match(view, /map\.on\("click", BADGES, onBadge\)/);
  // A dot a road while zoomed out, so a short road never vanishes; a white halo under every line.
  assert.match(view, /id: DOTS,\s*type: "circle"/);
  assert.match(view, /id: HALO,\s*type: "line"/);
  // A ruled road fades, as the server says.
  assert.match(view, /"line-opacity": \["case", \["get", "ruled"\], 0\.35, 1\]/);
  assert.match(view, /fetchNext\(origin, \{ lists/);
  assert.match(view, /aria-keyshortcuts=\{NEXT_KEYS\}/);
  assert.match(view, /const NEXT_KEYS = "Alt\+Shift\+N";/);
});

test("a pending agency's level is information only on the card, with a note by the reason", () => {
  const view = src("ReviewMode.tsx");
  assert.match(view, /\{!s\.pending && current\.actions\.includes\("set"\)/);
  assert.match(view, /Don&apos;t quote pending agencies&apos; data\./);
  // The card shows the road panel's street photo, from Review's own path; the list's rows ask for none.
  assert.equal(view.match(/<StreetPhotoView /g)?.length, 1);
  assert.doesNotMatch(view, /Street photo" \}/);
  // "Use" on a source's level sends the source, so the evidence names it.
  assert.match(view, /rule\("set", \[current\.osm_way_id\], s\.level, s\.key\)/);
  assert.match(view, /const PHOTO_PATH = "\/api\/review\/street-photo";/);
});

test("Review is an instance admin's alone", () => {
  const app = src("App.tsx");
  assert.match(app, /const canReview = me\.can_change_lts;/);
  assert.match(app, /const reviews = found\.can_change_lts;/);
  assert.doesNotMatch(app, /can_change_lts \|\| (me|found)\.can_review_closures/);
});

test("a stretch's row says the road, its pieces, its length in miles then kilometres, and its change", () => {
  const stretch = road(7, { name: "Oak Street", ways: [7, 8, 9], pieces: 3, length: "0.32 mi (0.52 km)", kind_label: "LTS 2 to LTS 4" });
  assert.equal(piecesText(stretch), "3 road pieces");
  assert.equal(roadRowLabel(stretch), "Oak Street, 3 road pieces, 0.32 mi (0.52 km): LTS 2 to LTS 4");
  // One way alone: no count; unnamed: its way; elsewhere the reason is the change.
  assert.equal(piecesText(road(7)), "");
  assert.equal(roadRowLabel(road(7)), "Way 7, 0.06 mi (0.10 km): LTS 4 to LTS 2");
  const rated = road(5, { queue: "disagreement", name: "Elm", reason: "RouteMaker's formula: LTS 4; DDOT: LTS 2", kind_label: "x" });
  assert.equal(roadRowLabel(rated), "Elm, 0.06 mi (0.10 km): RouteMaker's formula: LTS 4; DDOT: LTS 2");
  // The label starts with the name the button shows, so the name heard is the name seen.
  const source = readFileSync(new URL("../ReviewMode.tsx", import.meta.url), "utf8");
  assert.match(source, /aria-label=\{roadRowLabel\(road\)\}/);
  // A ruling on a stretch rules every way, each its own ruling: the count drops by the rows ruled.
  assert.match(source, /t - rowsRuled/);
});
