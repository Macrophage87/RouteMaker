// Rider suggestions (OWNER-DECISIONS 441h, 460.4, 460.5) and the spot link the Discord post carries.
import { test } from "node:test";
import assert from "node:assert/strict";
import { AT_ZOOM, atFromHash } from "./planHash.ts";
import {
  STEP_WORDS,
  fetchSuggestions,
  mapLink,
  QUICK_OTHER_MAX,
  fetchQuickTicket,
  quickProblem,
  quickValueText,
  sendQuick,
  reviewSuggestion,
  sendSuggestion,
  suggestProblem,
  suggestValueText,
  suggestionLine,
  talliesLine,
  sendVerdict,
  fetchMySuggestion,
  mySuggestionText,
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

test("v0.7.0 short form: the slider says each level, half steps as between two", () => {
  assert.equal(quickValueText(2), "2: Fine for adults");
  assert.equal(quickValueText(2.5), "Between 2 and 3: Fine for most confident adults");
  assert.equal(quickValueText(4.5), "Between 4 and Avoid: A very high-stress road");
  assert.equal(quickValueText(5), "Avoid");
});

test("v0.7.0 short form: no change, no reason or an empty Other is said before sending", () => {
  assert.equal(quickProblem(3, 3, ["calmer"], "")?.field, "step");
  assert.equal(quickProblem(2, 3, [], "")?.field, "reasons");
  assert.equal(quickProblem(2, 3, ["other"], "  ")?.field, "other");
  assert.equal(quickProblem(2, 3, ["other"], "x".repeat(QUICK_OTHER_MAX + 1))?.field, "other");
  assert.equal(quickProblem(2.5, 3, ["calmer"], ""), null);
  // v0.7.0 closures: "Closed" is a closure report, sent with the road's own level.
  assert.equal(quickProblem(3, 3, ["closed"], ""), null);
});

test("v0.7.0 short form: the ticket is asked for the road; ten a day is said plainly", async () => {
  const seen: string[] = [];
  const run = (async (url: string | URL | Request) => {
    seen.push(String(url));
    return new Response(JSON.stringify({ ticket: "t", reasons: [["calmer", "Feels calmer than rated"]] }), { status: 200 });
  }) as typeof fetch;
  const ticket = await fetchQuickTicket("https://x.test", 5001, run);
  assert.equal(ticket?.ticket, "t");
  assert.equal(seen[0], "https://x.test/api/stress-suggestions/ticket?way=5001");
  const limited = (async () => new Response(JSON.stringify({ error: "x" }), { status: 429 })) as typeof fetch;
  const body = { osm_way_id: 5001, lat: 1, lon: 2, step: 2, reasons: ["calmer"], other: "", ticket: "t", website: "" };
  const outcome = await sendQuick("https://x.test", body, "tok", limited);
  assert.equal(outcome.kind, "refused");
  assert.match(outcome.message, /10 suggestions today/);
});

// v0.7.0: a second reviewer's agree or disagree, and a rider's own suggestion's status.

test("the reviewers' tallies read in words, with their reasons and no names", () => {
  assert.equal(talliesLine(undefined), "");
  assert.equal(talliesLine({ agree: 0, disagree: 0, mine: null, notes: [] }), "");
  assert.equal(talliesLine({ agree: 1, disagree: 0, mine: "agree", notes: [] }), "Reviewers: 1 agrees, 0 disagree");
  assert.equal(
    talliesLine({ agree: 2, disagree: 1, mine: null, notes: [{ agree: false, reason: "The lane ends at Elm." }] }),
    "Reviewers: 2 agree, 1 disagrees (disagree: The lane ends at Elm.)",
  );
});

test("a verdict is posted with its trimmed reason and answers the new tallies", async () => {
  const seen: { url?: string; init?: RequestInit } = {};
  const reviews = { agree: 1, disagree: 0, mine: "agree", notes: [] };
  const r = await sendVerdict("https://rm.test", 7, "agree", "  fine  ", "tok", fakeFetch(200, { message: "ok", reviews }, seen));
  assert.equal(seen.url, "https://rm.test/api/stress-suggestions/7/review");
  assert.deepEqual(JSON.parse(String(seen.init?.body)), { verdict: "agree", reason: "fine" });
  assert.ok(r.ok && r.body.reviews.agree === 1);
  const refused = await sendVerdict("https://rm.test", 7, "disagree", "", null, fakeFetch(403, { error: "Only a RouteMaker reviewer can review a suggestion." }));
  assert.deepEqual(refused, { ok: false, message: "Only a RouteMaker reviewer can review a suggestion." });
});

test("a rider reads their own suggestion's status for the road", async () => {
  const mine = {
    id: 3,
    osm_way_id: 5001,
    step: 2,
    words: "Fine for adults",
    status: "pending",
    status_words: "Waiting for review.",
    created_at: "2026-10-16T12:00:00+00:00",
    decided_at: null,
  };
  const seen: { url?: string; init?: RequestInit } = {};
  const found = await fetchMySuggestion("https://rm.test", 5001, undefined, fakeFetch(200, { suggestion: mine }, seen));
  assert.equal(seen.url, "https://rm.test/api/stress-suggestions/mine?way=5001");
  assert.ok(found);
  assert.equal(mySuggestionText(found), "LTS 2 (Fine for adults). Waiting for review.");
  assert.equal(mySuggestionText({ ...found, step: 5, status_words: "Approved: the map uses it." }), "Avoid. Approved: the map uses it.");
  assert.equal(await fetchMySuggestion("https://rm.test", 5001, undefined, fakeFetch(200, { suggestion: null })), null);
  assert.equal(await fetchMySuggestion("https://rm.test", 5001, undefined, fakeFetch(401, { error: "Sign in" })), null);
});
