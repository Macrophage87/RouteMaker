// The road panel's stress editor, pure half and requests (OWNER-DECISIONS 441g, 441h; lib/stressEditor.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  AFTER_REBUILD,
  NO_ME,
  csrfFromCookie,
  currentText,
  countText,
  fetchEditorState,
  fetchMe,
  forgetMe,
  formProblem,
  levelPhrase,
  refusalText,
  saveEdit,
  savedSaid,
  shortDate,
  stepValueText,
  undoEdit,
  undoneSaid,
  type EditResult,
  type EditorCurrent,
  type EditorStep,
  type SaveRequest,
} from "./stressEditor.ts";

const STEPS: EditorStep[] = [
  { value: 1, words: "Comfortable for everyone" },
  { value: 2, words: "Fine for adults" },
  { value: 3, words: "For experienced cyclists" },
  { value: 4, words: "High stress: busy, fast traffic" },
  { value: 5, words: "Avoid" },
];

const REQUEST: SaveRequest = {
  osm_way_ids: [101],
  step: 4,
  at_least: false,
  category: "speed",
  reason: "r",
  display: "route_only",
  expected: "tok",
};

function reply(status: number, body: unknown): typeof fetch {
  return (async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch;
}

test("the slider reads as its words, the owner's wording (441l) for all five steps", () => {
  assert.equal(stepValueText(1, STEPS), "1, Comfortable for everyone");
  assert.equal(stepValueText(2, STEPS), "2, Fine for adults");
  assert.equal(stepValueText(3, STEPS), "3, For experienced cyclists");
  assert.equal(stepValueText(4, STEPS), "4, High stress: busy, fast traffic");
  assert.equal(stepValueText(5, STEPS), "5, Avoid");
  assert.equal(stepValueText(9, STEPS), "9");
});

test("a level in a sentence: Avoid is just Avoid (441j)", () => {
  assert.equal(levelPhrase(3, STEPS), "LTS 3, for experienced cyclists");
  assert.equal(levelPhrase(4, STEPS), "LTS 4, high stress: busy, fast traffic");
  assert.equal(levelPhrase(5, STEPS), "Avoid");
});

test("where the level now comes from is said once above the slider", () => {
  const base: EditorCurrent = {
    step: 3,
    words: "For experienced cyclists",
    source: "classifier",
    at_least: false,
    category: null,
    public_note: null,
    display: null,
    private_reason: null,
    when: null,
    by: null,
  };
  assert.equal(currentText(base, STEPS), "Now LTS 3, for experienced cyclists, from RouteMaker's classifier.");
  assert.match(currentText({ ...base, source: "file", at_least: true }, STEPS), /\(a floor: at least this\), from a reviewed override\.$/);
  assert.match(currentText({ ...base, source: "admin" }, STEPS), /from an override typed in the admin\.$/);
  const panel = currentText({ ...base, source: "panel", by: "you", when: "2026-10-09T15:00:00Z" }, STEPS);
  assert.match(panel, /from your change on Oct \d+\.$/);
  assert.match(currentText({ ...base, source: "panel", by: "another admin" }, STEPS), /from another admin's change/);
  assert.equal(shortDate("not a date"), "");
});

test("a save is said in a sentence: what changed, when the routes catch up, and the undo", () => {
  const result: EditResult = { edit_id: 1, ways: [{ osm_way_id: 101, step: 4, changed: true }], generation: 1, undo_until: "x" };
  const said = savedSaid(result, STEPS, false);
  assert.equal(said, `Changed to LTS 4, high stress: busy, fast traffic. ${AFTER_REBUILD} You can undo it for 30 minutes.`);
  assert.match(AFTER_REBUILD, /^The map shows it now; routes fully use it after the next weekly data update\.$/);
  const same = savedSaid({ ...result, ways: [{ osm_way_id: 101, step: 3, changed: false }] }, STEPS, false);
  assert.match(same, /^Saved\. This road already had LTS 3.*nothing changed on the map\./);
  const floor = savedSaid({ ...result, ways: [{ osm_way_id: 101, step: 4, changed: false }] }, STEPS, true);
  assert.match(floor, /^Saved\. This road is already at least that level, so nothing changed\./);
  assert.match(savedSaid({ ...result, ways: [] }, STEPS, false), /^Saved\./);
  assert.equal(
    undoneSaid({ ...result, ways: [{ osm_way_id: 101, step: 3, changed: true }] }, STEPS),
    "Undone. This road is back to LTS 3, for experienced cyclists.",
  );
  assert.equal(undoneSaid({ ...result, ways: [] }, STEPS), "Undone.");
});

test("the form is checked before it is sent: a private reason is required, and both texts have limits", () => {
  assert.deepEqual(formProblem({ reason: "  ", note: "" }, 500, 200)?.field, "reason");
  assert.match(formProblem({ reason: "", note: "" }, 500, 200)!.message, /private reason.*never shown to riders/i);
  assert.equal(formProblem({ reason: "x".repeat(501), note: "" }, 500, 200)?.field, "reason");
  assert.equal(formProblem({ reason: "ok", note: "n".repeat(201) }, 500, 200)?.field, "public_note");
  assert.equal(formProblem({ reason: "x".repeat(500), note: "n".repeat(200) }, 500, 200), null);
  assert.equal(formProblem({ reason: "ok", note: "   " }, 500, 200), null);
  assert.equal(countText("abc", 500), "3 of 500 characters");
});

test("the CSRF token is read from the page's own cookie", () => {
  assert.equal(csrfFromCookie("a=1; csrftoken=abc123; b=2"), "abc123");
  assert.equal(csrfFromCookie("csrftoken=a%20b"), "a b");
  assert.equal(csrfFromCookie("sessionid=x"), null);
  assert.equal(csrfFromCookie(""), null);
});

test("a refusal says what the server said where it wrote the sentence for an admin", () => {
  assert.equal(refusalText(409, "Someone changed this road since you opened it."), "Someone changed this road since you opened it.");
  assert.equal(refusalText(400, "A private reason is required."), "A private reason is required.");
  assert.match(refusalText(401, null), /signed out/);
  assert.match(refusalText(429, "Too many requests"), /Too many changes/);
  assert.match(refusalText(500, "Something went wrong"), /Nothing was changed/);
  assert.match(refusalText(0, null), /Nothing was changed/);
});

test("who is asking is asked once per page and fails closed", async () => {
  forgetMe();
  let asked = 0;
  const admin = (async () => {
    asked += 1;
    return new Response(JSON.stringify({ signed_in: true, can_change_lts: true, can_suggest: false }), { status: 200 });
  }) as unknown as typeof fetch;
  assert.deepEqual(await fetchMe("https://x.test", admin), { signed_in: true, can_change_lts: true, can_suggest: false });
  assert.deepEqual(await fetchMe("https://x.test", admin), { signed_in: true, can_change_lts: true, can_suggest: false });
  assert.equal(asked, 1);

  forgetMe();
  assert.deepEqual(await fetchMe("https://x.test", reply(500, {})), NO_ME);
  // A failure is not remembered: the next panel asks again.
  assert.deepEqual(await fetchMe("https://x.test", reply(200, { signed_in: true, can_change_lts: false, can_suggest: false })), {
    signed_in: true,
    can_change_lts: false,
    can_suggest: false,
  });
  forgetMe();
  // Anything but a strict true is a no.
  assert.deepEqual(await fetchMe("https://x.test", reply(200, { signed_in: "yes", can_change_lts: 1 })), NO_ME);
  forgetMe();
  assert.deepEqual(await fetchMe("https://x.test", (async () => { throw new Error("offline"); }) as unknown as typeof fetch), NO_ME);
  forgetMe();
});

test("the editor's starting state is asked without caching, and a refusal is a sentence", async () => {
  let seen: RequestInit | undefined;
  let url = "";
  const get = (async (u: string, init?: RequestInit) => {
    url = u;
    seen = init;
    return new Response(JSON.stringify({ osm_way_id: 101, expected: "tok" }), { status: 200 });
  }) as unknown as typeof fetch;
  const ready = await fetchEditorState("https://x.test", 101, undefined, get);
  assert.equal(url, "https://x.test/api/stress-edits/way/101");
  assert.equal(seen?.cache, "no-store");
  assert.equal(ready.kind, "ready");
  const denied = await fetchEditorState("https://x.test", 101, undefined, reply(403, { error: "Only an instance admin can change traffic stress." }));
  assert.deepEqual(denied, { kind: "error", message: "Only an instance admin can change traffic stress." });
  const down = await fetchEditorState("https://x.test", 101, undefined, reply(502, {}));
  assert.equal(down.kind, "error");
});

test("a save is a JSON POST with the CSRF header, never in a query string, and carries no person", async () => {
  let call: { url: string; init: RequestInit } | undefined;
  const post = (async (url: string, init: RequestInit) => {
    call = { url, init };
    return new Response(JSON.stringify({ edit_id: 7, ways: [], generation: 2, undo_until: "x" }), { status: 200 });
  }) as unknown as typeof fetch;
  const saved = await saveEdit("https://x.test", REQUEST, "tok123", post);
  assert.equal(saved.kind, "saved");
  assert.equal(call?.url, "https://x.test/api/stress-edits");
  assert.equal(call?.init.method, "POST");
  assert.ok(!call!.url.includes("?"));
  const headers = call?.init.headers as Record<string, string>;
  assert.equal(headers["X-CSRFToken"], "tok123");
  assert.equal(headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(String(call?.init.body)), REQUEST);
  // Without a token the header is left off (the server will say so).
  await saveEdit("https://x.test", REQUEST, null, post);
  assert.ok(!("X-CSRFToken" in (call?.init.headers as Record<string, string>)));
});

test("a refused save keeps the server's field and code, so the form can focus the field", async () => {
  const outcome = await saveEdit("https://x.test", REQUEST, "t", reply(400, { error: "A private reason is required.", field: "reason", code: "invalid" }));
  assert.deepEqual(outcome, { kind: "refused", status: 400, message: "A private reason is required.", field: "reason", code: "invalid" });
  const stale = await saveEdit("https://x.test", REQUEST, "t", reply(409, { error: "Someone changed this road.", code: "stale" }));
  assert.equal(stale.kind, "refused");
  if (stale.kind === "refused") assert.deepEqual([stale.status, stale.field, stale.code], [409, null, "stale"]);
  const offline = await saveEdit("https://x.test", REQUEST, "t", (async () => { throw new Error("offline"); }) as unknown as typeof fetch);
  assert.equal(offline.kind === "refused" && offline.status, 0);
});

test("undo posts to the change's own address with an empty JSON body", async () => {
  let call: { url: string; init: RequestInit } | undefined;
  const post = (async (url: string, init: RequestInit) => {
    call = { url, init };
    return new Response(JSON.stringify({ edit_id: 8, ways: [], generation: 3, undo_until: "x" }), { status: 200 });
  }) as unknown as typeof fetch;
  const outcome = await undoEdit("https://x.test", 7, "tok", post);
  assert.equal(outcome.kind, "saved");
  assert.equal(call?.url, "https://x.test/api/stress-edits/7/undo");
  assert.equal(call?.init.body, "{}");
});
