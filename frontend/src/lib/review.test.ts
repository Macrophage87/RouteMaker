// Review, the third view (lib/review.ts, lib/appMode.ts; the owner, 2026-10-16: "Basically we'd have 3 modes for
// people who have admin access go/plan/review").
import { test } from "node:test";
import assert from "node:assert/strict";
import { MODE_LABEL, isMode, isOpenIn, modeSaid, readLastReview, reopenReview, switchModes, writeLastReview } from "./appMode.ts";
import {
  DEFAULT_LIST,
  LISTS,
  decisionLabel,
  fetchRoads,
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
