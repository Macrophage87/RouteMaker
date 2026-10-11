// Rider suggestions (OWNER-DECISIONS 441h, 460.4, 460.5) and the spot link the Discord post carries.
import { test } from "node:test";
import assert from "node:assert/strict";
import { AT_ZOOM, atFromHash } from "./planHash.ts";
import {
  STEP_WORDS,
  fetchSuggestions,
  mapLink,
  reviewSuggestion,
  sendSuggestion,
  suggestProblem,
  suggestValueText,
  suggestionLine,
  type SuggestionItem,
} from "./suggestions.ts";

const ITEM: SuggestionItem = {
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

test("every step, half steps too, is read as its number and words", () => {
  assert.equal(Object.keys(STEP_WORDS).length, 9);
  assert.equal(suggestValueText(2.5), "2.5, Fine for most confident adults");
  assert.equal(suggestValueText(5), "5, Avoid");
});

test("the reason is required and at most 500 characters", () => {
  assert.equal(suggestProblem("  ")?.field, "reason");
  assert.equal(suggestProblem("x".repeat(501))?.field, "reason");
  assert.equal(suggestProblem("A protected lane opened."), null);
});

test("a suggestion is posted as JSON with the CSRF token; a refusal names its field", async () => {
  const seen: { url?: string; init?: RequestInit } = {};
  const sent = await sendSuggestion("https://x.test", { osm_way_id: 1, lat: 38.9, lon: -77, step: 2.5, reason: "r" }, "tok", fakeFetch(200, { message: "Thanks." }, seen));
  assert.deepEqual(sent, { kind: "sent", message: "Thanks." });
  assert.equal(seen.url, "https://x.test/api/stress-suggestions");
  assert.equal((seen.init?.headers as Record<string, string>)["X-CSRFToken"], "tok");
  assert.equal(JSON.parse(String(seen.init?.body)).step, 2.5);
  const refused = await sendSuggestion("https://x.test", { osm_way_id: 1, lat: 38.9, lon: -77, step: 3, reason: "r" }, "tok", fakeFetch(400, { error: "That is the road's level already.", field: "step" }));
  assert.deepEqual(refused, { kind: "refused", status: 400, message: "That is the road's level already.", field: "step" });
});

test("the review list and an action", async () => {
  const list = await fetchSuggestions("https://x.test", fakeFetch(200, { suggestions: [ITEM] }));
  assert.ok(Array.isArray(list) && list[0].road === "Oak Street");
  const seen: { url?: string; init?: RequestInit } = {};
  const r = await reviewSuggestion("https://x.test", 7, "discord", "tok", fakeFetch(200, { post: "p" }, seen));
  assert.ok(r.ok);
  assert.equal(seen.url, "https://x.test/api/stress-suggestions/7/discord");
  assert.equal(seen.init?.method, "POST");
  const no = await reviewSuggestion("https://x.test", 7, "approve", "tok", fakeFetch(409, { error: "That suggestion was deleted already." }));
  assert.deepEqual(no, { ok: false, message: "That suggestion was deleted already." });
});

test("a suggestion's heading names the road and both levels in words", () => {
  assert.equal(suggestionLine(ITEM), "Oak Street: from LTS 3 (For experienced cyclists) to LTS 2.5 (Fine for most confident adults)");
  assert.equal(suggestionLine({ ...ITEM, step: 5, words: "Avoid" }), "Oak Street: from LTS 3 (For experienced cyclists) to Avoid");
});

test("the spot link opens the map at the spot, street level, and only inside the covered area", () => {
  const link = mapLink("https://x.test", ITEM);
  assert.equal(link, "https://x.test/#at=-77.02900,38.89900");
  assert.deepEqual(atFromHash(link.slice(link.indexOf("#"))), [-77.029, 38.899]);
  assert.equal(AT_ZOOM, 16);
  assert.equal(atFromHash("#at=0,0"), null);
  assert.equal(atFromHash("#at=nonsense"), null);
  assert.equal(atFromHash("#p=-77.04,38.91"), null);
});

test("the privacy note says the road's location may be shared, and never the rider's name or spot", async () => {
  const { SUGGEST_PRIVACY } = await import("./suggestions.ts");
  assert.match(SUGGEST_PRIVACY, /road's location/);
  assert.match(SUGGEST_PRIVACY, /never your name or the spot you clicked/);
});
