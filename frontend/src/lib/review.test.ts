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
  besideInOrder,
  decisionLabel,
  fetchMap,
  fetchRoadDetail,
  fetchRoads,
  makeAnnouncer,
  nextDiscrepancy,
  progressText,
  roadHeading,
  ruledSaid,
  sendRuling,
  sortRoads,
  stepText,
  trafficText,
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

test("Next discrepancy: the next road with no ruling, in its list's order, then the next list shown, then round", () => {
  const orders = { rebuild: [1, 2, 3], disagreement: [10, 11], sidepath: [20] };
  const ruled = { rebuild: new Set([2]), disagreement: new Set([10]) };
  const all = new Set(QUEUES);
  assert.deepEqual(nextDiscrepancy(orders, ruled, all, { queue: "rebuild", way: 1 }), { queue: "rebuild", way: 3 });
  assert.deepEqual(nextDiscrepancy(orders, ruled, all, { queue: "rebuild", way: 3 }), { queue: "disagreement", way: 11 });
  // A list switched off on the map is passed over.
  const noDisagreements = new Set(QUEUES.filter((q) => q !== "disagreement"));
  assert.deepEqual(nextDiscrepancy(orders, ruled, noDisagreements, { queue: "rebuild", way: 3 }), { queue: "sidepath", way: 20 });
  // Round to the start of the first list.
  assert.deepEqual(nextDiscrepancy(orders, ruled, all, { queue: "sidepath", way: 20 }), { queue: "rebuild", way: 1 });
  assert.deepEqual(nextDiscrepancy(orders, ruled, all, null), { queue: "rebuild", way: 1 });
  // Round within the one list shown, to a road before the one open.
  assert.deepEqual(nextDiscrepancy({ rebuild: [1, 2, 3] }, {}, all, { queue: "rebuild", way: 3 }), { queue: "rebuild", way: 1 });
  // Everything ruled: nothing.
  assert.equal(nextDiscrepancy({ rebuild: [1] }, { rebuild: new Set([1]) }, all, null), null);
  assert.equal(nextDiscrepancy(orders, ruled, new Set(), null), null);
});

test("Previous and Next from a road off the page: the road beside it in its list's order", () => {
  assert.equal(besideInOrder([5, 6, 7], 6, 1), 7);
  assert.equal(besideInOrder([5, 6, 7], 6, -1), 5);
  assert.equal(besideInOrder([5, 6, 7], 7, 1), null);
  assert.equal(besideInOrder([5, 6, 7], 9, 1), null);
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

test("the map is asked for whole lists, once a detail, and the road's facts with the new build's for a rebuild", async () => {
  const asked: string[] = [];
  const run = (async (url: string) => {
    asked.push(url);
    return new Response(JSON.stringify({ queue: "rebuild", ruled: [], lines: { type: "FeatureCollection", features: [] }, points: { type: "FeatureCollection", features: [] } }), { status: 200 });
  }) as typeof fetch;
  await fetchMap("https://x", "rebuild", "low", run);
  await fetchMap("https://x", "disagreement", "high", run);
  await fetchRoadDetail("https://x", 5, "rebuild", run);
  await fetchRoadDetail("https://x", 6, null, run);
  assert.deepEqual(asked, [
    "https://x/api/review/map?queue=rebuild&detail=low",
    "https://x/api/review/map?queue=disagreement&detail=high",
    "https://x/api/review/road/5?queue=rebuild",
    "https://x/api/review/road/6",
  ]);
});

test("Review's map draws every list bold above the stress lines from a region's view, with count badges further out", () => {
  const view = src("ReviewMode.tsx");
  assert.match(view, /const LINE_MIN_ZOOM = 7\.5;/);
  assert.match(view, /cluster: true, clusterMaxZoom: CLUSTER_MAX_ZOOM/);
  assert.match(view, /getClusterExpansionZoom/);
  // A dot a road while zoomed out, so a short road never vanishes; a white halo under every line.
  assert.match(view, /id: DOTS,\s*type: "circle"/);
  assert.match(view, /id: HALO,\s*type: "line"/);
  // No per-request bounding-box query: the lists' maps are read whole, as computed.
  assert.doesNotMatch(view, /fetchOverlay|getBounds/);
  assert.match(view, /aria-keyshortcuts=\{NEXT_KEYS\}/);
  assert.match(view, /const NEXT_KEYS = "Alt\+Shift\+N";/);
});

test("a pending agency's level is information only on the card, with a note by the reason", () => {
  const view = src("ReviewMode.tsx");
  assert.match(view, /\{!s\.pending && current\.actions\.includes\("set"\)/);
  assert.match(view, /Don&apos;t quote pending agencies&apos; data\./);
  // The rows and the card show the road panel's street photo, from Review's own path.
  assert.match(view, /<StreetPhotoView compact title=\{name\}/);
  assert.match(view, /const PHOTO_PATH = "\/api\/review\/street-photo";/);
});

test("Review is an instance admin's alone", () => {
  const app = src("App.tsx");
  assert.match(app, /const canReview = me\.can_change_lts;/);
  assert.match(app, /const reviews = found\.can_change_lts;/);
  assert.doesNotMatch(app, /can_change_lts \|\| (me|found)\.can_review_closures/);
});
