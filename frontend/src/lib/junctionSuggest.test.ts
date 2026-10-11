// Rider suggestions for junctions (FOLLOWUP-STRESS-SUGGEST, OWNER-DECISIONS 232) and the admin's one review list.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  JUNCTION_LEVELS,
  JUNCTION_PRIVACY,
  SHOWN_LEVELS,
  avoidWarning,
  fetchJunctionSuggestions,
  findJunction,
  junctionEntry,
  junctionLine,
  junctionNote,
  junctionProblem,
  levelWords,
  loadProblem,
  reviewEntries,
  reviewJunctionSuggestion,
  sendJunctionSuggestion,
  shownNear,
  type JunctionSuggestionItem,
} from "./junctionSuggest.ts";
import type { SuggestionItem } from "./suggestions.ts";

const JUNCTION: JunctionSuggestionItem = {
  id: 3,
  junction: "Oak Street and Elm Street",
  lat: 38.899,
  lon: -77.03,
  current_level: 3,
  current_words: "Takes patience: you wait for a gap",
  level: 4,
  words: "Hard: long waits or fast traffic",
  direction: "more",
  reason: "Drivers turn right on red without looking.",
  status: "pending",
  created_at: "2026-10-10T15:00:00+00:00",
  sent_at: null,
};

const ROAD: SuggestionItem = {
  id: 7,
  osm_way_id: 5001,
  road: "Oak Street",
  lat: 38.899,
  lon: -77.029,
  current_step: 3,
  current_words: "For experienced cyclists",
  step: 2.5,
  words: "Fine for most confident adults",
  reason: "A protected lane opened.",
  status: "pending",
  created_at: "2026-10-10T14:00:00+00:00",
  sent_at: null,
};

function fakeFetch(status: number, body: unknown, seen: { url?: string; init?: RequestInit } = {}) {
  return (async (url: string, init?: RequestInit) => {
    seen.url = url;
    seen.init = init;
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
}

test("the levels are the poll's plain words, Avoid included, and never an LTS number", () => {
  assert.deepEqual(
    JUNCTION_LEVELS.map((l) => l.level),
    [2, 3, 4, 5],
  );
  assert.equal(levelWords(5), "Avoid crossing here");
  assert.ok(JUNCTION_LEVELS.every((l) => !/LTS/.test(l.words)));
  assert.deepEqual(SHOWN_LEVELS, { none: 2, orange: 3, red: 4, avoid: 5 });
});

test("what the route shows nearest the spot: Avoid first, then the worst marker, within 82 ft (25 m)", () => {
  const route = {
    intersections: [
      { lon: -77.03, lat: 38.9, severity: "orange" as const },
      { lon: -77.0301, lat: 38.9, severity: "red" as const },
    ],
    avoid_junctions: [],
  } as unknown as Parameters<typeof shownNear>[0];
  assert.equal(shownNear(route, [-77.03, 38.9]), "red");
  // About 44 m (144 ft) north: nothing shown there.
  assert.equal(shownNear(route, [-77.03, 38.9004]), "none");
  assert.equal(shownNear(null, [-77.03, 38.9]), null);
  const avoid = { intersections: [], avoid_junctions: [{ lon: -77.03, lat: 38.9 }] } as unknown as Parameters<typeof shownNear>[0];
  assert.equal(shownNear(avoid, [-77.03005, 38.9]), "avoid");
});

test("the form's own check: a choice, a comparison that agrees with the map, and a reason", () => {
  assert.equal(junctionProblem(null, null, "r", "orange")?.field, "level");
  assert.equal(junctionProblem(3, null, "r", "orange")?.field, "level");
  assert.equal(junctionProblem(2, "more", "r", "orange")?.field, "direction");
  assert.equal(junctionProblem(null, "more", "r", "avoid")?.field, "direction");
  assert.equal(junctionProblem(null, "less", "r", null)?.field, "direction");
  assert.equal(junctionProblem(4, null, " ", "orange")?.field, "reason");
  assert.equal(junctionProblem(4, null, "x".repeat(501), "orange")?.field, "reason");
  assert.equal(junctionProblem(5, "more", "Cars run the light.", "red"), null);
  assert.equal(junctionProblem(null, "less", "A signal went in.", "red"), null);
});

test("the junction is asked for at the spot; a refusal or no junction there is null", async () => {
  const seen: { url?: string; init?: RequestInit } = {};
  const found = await findJunction("https://x.test", [-77.03, 38.899], undefined, fakeFetch(200, { lon: -77.03, lat: 38.899, name: "A and B", roads: ["A", "B"] }, seen));
  assert.equal(found?.name, "A and B");
  assert.equal(seen.url, "https://x.test/api/junction-suggestions/at?lat=38.899000&lon=-77.030000");
  assert.equal(await findJunction("https://x.test", [-77, 38.9], undefined, fakeFetch(400, { error: "no junction" })), null);
});

test("a suggestion sends the junction's node, never the spot, with the CSRF token; a refusal names its field", async () => {
  const seen: { url?: string; init?: RequestInit } = {};
  const request = { lat: 38.899, lon: -77.03, level: null, direction: "more" as const, shown: "orange" as const, reason: "r" };
  const sent = await sendJunctionSuggestion("https://x.test", request, "tok", fakeFetch(200, { message: "Thanks." }, seen));
  assert.deepEqual(sent, { kind: "sent", message: "Thanks." });
  assert.equal(seen.url, "https://x.test/api/junction-suggestions");
  assert.equal((seen.init?.headers as Record<string, string>)["X-CSRFToken"], "tok");
  assert.deepEqual(JSON.parse(String(seen.init?.body)), request);
  const refused = await sendJunctionSuggestion("https://x.test", request, "tok", fakeFetch(400, { error: "That is how the map shows it already.", field: "level" }));
  assert.deepEqual(refused, { kind: "refused", status: 400, message: "That is how the map shows it already.", field: "level" });
});

test("the admin's list and actions go to the junction endpoints", async () => {
  const list = await fetchJunctionSuggestions("https://x.test", fakeFetch(200, { suggestions: [JUNCTION] }));
  assert.ok(Array.isArray(list) && list[0].junction === "Oak Street and Elm Street");
  const seen: { url?: string; init?: RequestInit } = {};
  assert.ok((await reviewJunctionSuggestion("https://x.test", 3, "approve", "tok", fakeFetch(200, { message: "m" }, seen))).ok);
  assert.equal(seen.url, "https://x.test/api/junction-suggestions/3/approve");
  const no = await reviewJunctionSuggestion("https://x.test", 3, "delete", "tok", fakeFetch(409, { error: "That suggestion was approved already." }));
  assert.deepEqual(no, { ok: false, message: "That suggestion was approved already." });
});

test("a junction's heading names its roads and both levels in words; roads and junctions are one list, oldest first", () => {
  assert.equal(junctionLine(JUNCTION), "Junction of Oak Street and Elm Street: from Takes patience to Hard");
  assert.equal(junctionLine({ ...JUNCTION, junction: "An unnamed junction", level: 5 }), "An unnamed junction: from Takes patience to Avoid");
  const entries = reviewEntries([ROAD], [JUNCTION]);
  assert.deepEqual(
    entries.map((e) => e.key),
    ["road-7", "junction-3"],
  );
  assert.equal(entries[1].detail, "The rider said: more dangerous than shown.");
  assert.equal(entries[0].detail, "");
  assert.equal(entries[1].place, "the junction of Oak Street and Elm Street");
  assert.equal(entries[0].place, ROAD.road);
});

test("the button's note names the junction; the privacy note says only its location may be shared", () => {
  assert.equal(junctionNote("Oak Street and Elm Street"), "for the junction of Oak Street and Elm Street.");
  assert.equal(junctionNote("An unnamed junction"), "for this unnamed junction.");
  assert.match(JUNCTION_PRIVACY, /junction's location/);
  assert.match(JUNCTION_PRIVACY, /never your name or the spot you clicked/);
});

test("approving a level short of Avoid where Avoid is approved warns first; anything else approves at once", () => {
  assert.equal(junctionEntry(JUNCTION).warning, "");
  assert.equal(junctionEntry({ ...JUNCTION, withdraws_avoid: 0 }).warning, "");
  const one = junctionEntry({ ...JUNCTION, withdraws_avoid: 1 }).warning;
  assert.match(one, /^Approving this withdraws the approved Avoid rating here\. .*Approve anyway\?$/);
  assert.match(avoidWarning(2), /withdraws the 2 approved Avoid ratings here/);
  assert.equal(avoidWarning(0), "");
});

test("a list that did not load is named: roads, junctions or both", () => {
  assert.equal(loadProblem([], []), "");
  assert.equal(loadProblem("Could not reach the server.", []), "Road suggestions could not load. Could not reach the server.");
  assert.equal(loadProblem([], "Not allowed."), "Junction suggestions could not load. Not allowed.");
  assert.equal(loadProblem("A.", "B."), "Road suggestions could not load. A. Junction suggestions could not load. B.");
});
