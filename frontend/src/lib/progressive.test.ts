/**
 * v0.7.0, "Faster routing, mainly for Go": Go's first route then its full plan (lib/progressive.ts and the scheduler's
 * `refine`), Go's early start, and how App wires them (one line said once, no focus moved, never mid-ride).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { betterRouteSaid, CALMER_BY_M, EarlyStart, EARLY_PER_MINUTE, sameRoute, takesRefined } from "./progressive.ts";
import { newPlanId, RouteScheduler, type SchedulerState, type Timers } from "./routeScheduler.ts";
import { cancelRoute, describeError, requestRoute, routeRequestBody, type RouteResponse, type RouteResult } from "./api.ts";
import { noviceOfferShown } from "./noviceOffer.ts";

type Line = Pick<RouteResponse, "geometry" | "distance_m" | "duration_s" | "stress_m">;

function line(coords: [number, number][], seconds: number, busy: number): Line {
  return {
    geometry: { type: "LineString", coordinates: coords },
    distance_m: 1000 * (coords.length - 1),
    duration_s: seconds,
    stress_m: { "1": 500, "3": busy },
  };
}

const A: [number, number][] = [
  [-77.04, 38.9],
  [-77.03, 38.9],
];
const B: [number, number][] = [
  [-77.04, 38.9],
  [-77.035, 38.905],
  [-77.03, 38.9],
];

test("the same line is swapped in silently", () => {
  assert.equal(sameRoute(line(A, 600, 300), line(A, 600, 300)), true);
  assert.equal(betterRouteSaid(line(A, 600, 300), line(A, 600, 300)), null);
  assert.equal(sameRoute(line(A, 600, 300), line(B, 600, 300)), false);
});

test("a calmer route is said as calmer, with the minutes it adds", () => {
  assert.equal(betterRouteSaid(line(A, 600, 900), line(B, 720, 900 - CALMER_BY_M)), "Found a calmer route, +2 min.");
  assert.equal(betterRouteSaid(line(A, 600, 900), line(B, 610, 0)), "Found a calmer route.");
});

test("a quicker route, and otherwise a better one", () => {
  assert.equal(betterRouteSaid(line(A, 600, 300), line(B, 420, 300)), "Found a quicker route, 3 min less.");
  assert.equal(betterRouteSaid(line(A, 600, 300), line(B, 640, 300)), "Found a better route, +1 min.");
});

test("only a first route is replaced, and never once Start is pressed", () => {
  assert.equal(takesRefined({ provisional: true }, false), true);
  assert.equal(takesRefined({ provisional: false }, false), false);
  assert.equal(takesRefined({}, false), false);
  assert.equal(takesRefined(null, false), false);
  assert.equal(takesRefined({ provisional: true }, true), false, "riding");
});

test("Novice and Nervous's offer waits for the full plan", () => {
  const note = { busy_m: 900, busiest: null, over_ceiling: false, transit: true };
  assert.equal(noviceOfferShown({ novice: note }, "novice"), true);
  assert.equal(noviceOfferShown({ novice: note, provisional: true }, "novice"), false);
});

test("the request body says quick only when asked, so it keys the early start exactly", () => {
  const points: [number, number][] = [
    [-77.04, 38.9],
    [-77.03, 38.91],
  ];
  const plain = JSON.parse(routeRequestBody(points, "default", {}));
  assert.equal("quick" in plain, false);
  const quick = JSON.parse(routeRequestBody(points, "default", { quick: true }));
  assert.equal(quick.quick, true);
  assert.equal(routeRequestBody(points, "default", { quick: true }), routeRequestBody(points, "default", { quick: true }));
});

test("a ride's re-plan asks for the route alone, and nothing else does (review speed-5)", () => {
  const points: [number, number][] = [
    [-77.04, 38.9],
    [-77.03, 38.91],
  ];
  assert.equal("candidates" in JSON.parse(routeRequestBody(points, "default", {})), false);
  assert.equal(JSON.parse(routeRequestBody(points, "default", { routeOnly: true })).candidates, false);
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  const calls = ride.match(/requestRoute\([^;]*\);/g) ?? [];
  assert.equal(calls.length, 1);
  assert.match(calls[0], /routeOnly: true/);
  // A closure's detour uses the line alone too.
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const reroute = app.slice(app.indexOf("const closureReroute"), app.indexOf("const downloadRoute"));
  assert.match(reroute, /requestRoute\([^;]*routeOnly: true[^;]*\);/);
});

// --- The scheduler's refine ------------------------------------------------------------------

class FakeTimers implements Timers {
  now = 0;
  private next = 1;
  private pending = new Map<number, { at: number; fn: () => void }>();
  set = (fn: () => void, ms: number) => {
    const id = this.next++;
    this.pending.set(id, { at: this.now + ms, fn });
    return id;
  };
  clear = (handle: unknown) => {
    this.pending.delete(handle as number);
  };
  async advance(ms: number) {
    const until = this.now + ms;
    for (;;) {
      const due = [...this.pending.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      this.pending.delete(due[0]);
      this.now = due[1].at;
      due[1].fn();
      await flush();
    }
    this.now = until;
    await flush();
  }
}

async function flush() {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
}

const FIRST = { distance_m: 1, provisional: true } as RouteResponse;
const FULL = { distance_m: 2, provisional: false } as RouteResponse;

/** A scheduler whose sends and refines wait for the test to answer them. */
function setup() {
  const timers = new FakeTimers();
  const waiting: Array<{ kind: "send" | "refine"; plan: number; answer: (r: RouteResult) => void }> = [];
  let inFlight = 0;
  let most = 0;
  const call = (kind: "send" | "refine", plan: number) =>
    new Promise<RouteResult>((resolve) => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      waiting.push({
        kind,
        plan,
        answer: (r) => {
          inFlight -= 1;
          resolve(r);
        },
      });
    });
  const shown: Array<{ plan: number; route: RouteResponse | null }> = [];
  const refined: Array<{ plan: number; route: RouteResponse | null }> = [];
  const states: SchedulerState[] = [];
  const scheduler = new RouteScheduler<number>({
    send: (plan) => call("send", plan),
    refine: (plan, first) => (first.ok && first.route.provisional ? () => call("refine", plan) : null),
    onResult: (plan, result) => shown.push({ plan, route: result.ok ? result.route : null }),
    onRefined: (plan, result) => refined.push({ plan, route: result.ok ? result.route : null }),
    onState: (s) => states.push(s),
    timers,
  });
  return { timers, waiting, shown, refined, states, scheduler, most: () => most };
}

test("a first route is shown at once and its full plan follows as the one request in flight", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  assert.deepEqual(t.waiting.map((w) => w.kind), ["send"]);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(t.shown, [{ plan: 1, route: FIRST }]);
  assert.deepEqual(t.waiting.map((w) => w.kind), ["send", "refine"]);
  assert.equal(t.scheduler.busy(), true);
  t.waiting[1].answer({ ok: true, route: FULL });
  await flush();
  assert.deepEqual(t.refined, [{ plan: 1, route: FULL }]);
  assert.equal(t.scheduler.busy(), false);
  assert.equal(t.most(), 1, "one request at a time");
});

test("a full plan is not asked for after a full plan", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FULL });
  await flush();
  assert.equal(t.waiting.length, 1);
  assert.equal(t.scheduler.busy(), false);
});

test("a plan changed while its full plan is computed: the full plan is dropped, the new plan waits, then goes", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.request(2);
  // Said to be coming, though it waits for the slot.
  assert.deepEqual(t.states.at(-1), { kind: "pending" });
  await t.timers.advance(1000);
  assert.equal(t.waiting.length, 2, "never two at once: the new plan waits for the full plan");
  t.waiting[1].answer({ ok: true, route: FULL });
  await flush();
  assert.deepEqual(t.refined, [], "the full plan of a plan no longer asked for is not shown");
  assert.deepEqual(t.waiting.map((w) => [w.kind, w.plan]), [
    ["send", 1],
    ["refine", 1],
    ["send", 2],
  ]);
  assert.equal(t.most(), 1);
});

test("a refused full plan leaves the first route, and its Retry-After holds the next request", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.waiting[1].answer({ ok: false, error: describeError(429, null, "3") });
  await flush();
  assert.deepEqual(t.refined, []);
  assert.deepEqual(t.shown.map((s) => s.route), [FIRST]);
  t.scheduler.request(2);
  await t.timers.advance(2500);
  assert.equal(t.waiting.length, 2, "held by the Retry-After");
  await t.timers.advance(1000);
  assert.equal(t.waiting.length, 3);
});

test("cleared while the full plan computes: nothing is shown and the planner is idle", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.clear();
  t.waiting[1].answer({ ok: true, route: FULL });
  await flush();
  assert.deepEqual(t.refined, []);
  assert.deepEqual(t.states.at(-1), { kind: "idle" });
});

// --- A full plan replaced and cancelled (routing audit S7, option B; the owner, 2026-10-27) ----------------------

/** `setup`, with the API able to stop a full plan: what was sent, with its ids, and what was cancelled. */
function setupCancel() {
  const timers = new FakeTimers();
  const waiting: Array<{ kind: "send" | "refine"; plan: number; id?: string; answer: (r: RouteResult) => void }> = [];
  const cancelled: string[] = [];
  let ids = 0;
  const call = (kind: "send" | "refine", plan: number, id?: string) =>
    new Promise<RouteResult>((resolve) => {
      waiting.push({ kind, plan, id, answer: resolve });
    });
  const shown: Array<{ plan: number; route: RouteResponse | null }> = [];
  const refined: Array<{ plan: number; route: RouteResponse | null }> = [];
  const states: SchedulerState[] = [];
  const scheduler = new RouteScheduler<number>({
    send: (plan, replaces) => call("send", plan, replaces),
    refine: (plan, first, planId) => (first.ok && first.route.provisional ? () => call("refine", plan, planId) : null),
    cancel: (planId) => cancelled.push(planId),
    planId: () => `plan-${(ids += 1)}`,
    onResult: (plan, result) => shown.push({ plan, route: result.ok ? result.route : null }),
    onRefined: (plan, result) => refined.push({ plan, route: result.ok ? result.route : null }),
    onState: (s) => states.push(s),
    timers,
  });
  return { timers, waiting, cancelled, shown, refined, states, scheduler };
}

test("a plan changed while its full plan runs cancels it and goes after the debounce, naming it", async () => {
  const t = setupCancel();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(t.waiting.map((w) => [w.kind, w.plan, w.id]), [
    ["send", 1, undefined],
    ["refine", 1, "plan-1"],
  ]);
  t.scheduler.request(2);
  assert.deepEqual(t.cancelled, ["plan-1"], "cancelled at once, not when the new plan goes");
  assert.equal(t.waiting.length, 2, "the debounce still folds a burst of edits");
  await t.timers.advance(300);
  // Before: the new plan waited for the full plan's answer, then went.
  assert.deepEqual(t.waiting.map((w) => [w.kind, w.plan, w.id]).at(-1), ["send", 2, "plan-1"]);
});

test("a replaced full plan's answer is never read, its refusal and Retry-After included", async () => {
  const t = setupCancel();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.request(2, { now: true });
  await flush();
  t.waiting[1].answer({ ok: false, error: describeError(409, { error: "replaced", code: "plan_cancelled" }, null) });
  await flush();
  t.waiting[2].answer({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(t.refined, []);
  assert.deepEqual(t.shown.map((s) => s.plan), [1, 2]);
  // Plan 2's own full plan went, and is shown.
  assert.deepEqual(t.waiting.map((w) => [w.kind, w.plan, w.id]).at(-1), ["refine", 2, "plan-2"]);
  t.waiting[3].answer({ ok: true, route: FULL });
  await flush();
  assert.deepEqual(t.refined, [{ plan: 2, route: FULL }]);
  assert.equal(t.scheduler.busy(), false);

  // A late 429 with Retry-After from a replaced full plan holds nothing back.
  t.scheduler.request(3, { now: true });
  await flush();
  t.waiting[4].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.request(4, { now: true });
  await flush();
  t.waiting[5].answer({ ok: false, error: describeError(429, null, "30") });
  await flush();
  assert.equal(t.waiting.length, 7, "plan 4 went at once");
  assert.deepEqual([t.waiting[6].kind, t.waiting[6].plan], ["send", 4]);
});

test("a first route in flight is still waited for: only a full plan is replaced", async () => {
  const t = setupCancel();
  t.scheduler.request(1, { now: true });
  await flush();
  t.scheduler.request(2, { now: true });
  await flush();
  assert.equal(t.waiting.length, 1);
  assert.deepEqual(t.cancelled, []);
});

test("cleared while the full plan runs: cancelled, and nothing is named as replaced", async () => {
  const t = setupCancel();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.clear();
  assert.deepEqual(t.cancelled, ["plan-1"]);
  assert.equal(t.scheduler.busy(), false, "Go's early start may go");
  assert.deepEqual(t.states.at(-1), { kind: "idle" });
  t.scheduler.request(2, { now: true });
  await flush();
  assert.deepEqual(t.waiting.map((w) => [w.kind, w.plan, w.id]).at(-1), ["send", 2, undefined]);
});

test("the early start waits until the plan replacing a full plan is sent", async () => {
  const t = setupCancel();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.request(2);
  assert.equal(t.scheduler.busy(), true, "the replaced plan may still hold its slot");
  await t.timers.advance(300);
  t.waiting[2].answer({ ok: true, route: FULL });
  await flush();
  assert.equal(t.scheduler.busy(), false);
});

test("the plan replacing a full plan names it on every resend and outwaits MAX_WAITS while the slot is held", async () => {
  const t = setupCancel();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.request(2, { now: true });
  await flush();
  // The old plan holds the client's slot through more refusals than MAX_WAITS (3) allows.
  for (let i = 0; i < 6; i += 1) {
    const last = t.waiting.at(-1)!;
    assert.deepEqual([last.kind, last.plan, last.id], ["send", 2, "plan-1"], `resend ${i} still names the plan it replaces`);
    last.answer({ ok: false, error: describeError(429, null, "2") });
    await flush();
    assert.equal(t.scheduler.busy(), true);
    await t.timers.advance(2000);
  }
  assert.deepEqual(t.shown.map((s) => s.plan), [1], "no refusal shown while the old plan unwinds");
  t.waiting.at(-1)!.answer({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(t.shown.map((s) => s.plan), [1, 2]);
  // The slot is back: plan 2's own full plan names nothing, and Go's early start may go once it settles.
  const refine = t.waiting.at(-1)!;
  assert.deepEqual([refine.kind, refine.plan, refine.id], ["refine", 2, "plan-2"]);
  refine.answer({ ok: true, route: FULL });
  await flush();
  assert.equal(t.scheduler.busy(), false);
});

test("the replacing plan's patience ends: past REPLACE_PATIENCE_S, the usual MAX_WAITS, then the refusal", async () => {
  const t = setupCancel();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.request(2, { now: true });
  await flush();
  let sends = 0;
  while (t.shown.length < 2 && sends < 100) {
    t.waiting.at(-1)!.answer({ ok: false, error: describeError(429, null, "10") });
    await flush();
    sends += 1;
    await t.timers.advance(10_000);
  }
  // 50 s of Retry-After (5 sends), then MAX_WAITS more resends, then shown.
  assert.equal(sends, 5 + 3 + 1);
  assert.deepEqual(t.shown.map((s) => [s.plan, s.route]), [
    [1, FIRST],
    [2, null],
  ]);
  assert.equal(t.scheduler.busy(), false, "a refusal shown names no replaced plan any more");
});

test("a plan changed again while the replacing plan is refused still names the cancelled plan", async () => {
  const t = setupCancel();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.scheduler.request(2, { now: true });
  await flush();
  t.scheduler.request(3, { now: true });
  t.waiting.at(-1)!.answer({ ok: false, error: describeError(503, null, "2") });
  await flush();
  await t.timers.advance(2000);
  const last = t.waiting.at(-1)!;
  assert.deepEqual([last.kind, last.plan, last.id], ["send", 3, "plan-1"]);
});

test("Go's full plan carries its id and the plan replacing it names it, as headers only", async () => {
  const seen: RequestInit[] = [];
  const fetchImpl = async (_url: string, init: RequestInit) => {
    seen.push(init);
    return new Response("{}", { status: 500 });
  };
  const points: [number, number][] = [
    [-77.04, 38.9],
    [-77.03, 38.91],
  ];
  await requestRoute(points, "default", { planId: "abcdef0123456789", fetchImpl });
  await requestRoute(points, "default", { replaces: "abcdef0123456789", fetchImpl });
  await requestRoute(points, "default", { fetchImpl });
  const headers = seen.map((init) => init.headers as Record<string, string>);
  assert.equal(headers[0]["X-Plan-Id"], "abcdef0123456789");
  assert.equal(headers[1]["X-Plan-Replaces"], "abcdef0123456789");
  assert.equal("X-Plan-Id" in headers[2] || "X-Plan-Replaces" in headers[2], false);
  assert.equal(seen[0].body, seen[2].body, "the body, and so the early start's key, is the same");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /cancel: \(planId: string\) => cancelRoute\(planId\)/);
});

test("a cancel is fired and forgotten, and a failure is swallowed", async () => {
  const sent: Array<{ url: string; init: RequestInit }> = [];
  cancelRoute("abcdef0123456789", {
    fetchImpl: async (url, init) => {
      sent.push({ url, init });
      throw new Error("offline");
    },
  });
  await flush();
  assert.equal(sent[0].url, "/api/route/cancel");
  assert.deepEqual(JSON.parse(sent[0].init.body as string), { plan_id: "abcdef0123456789" });
  assert.equal(sent[0].init.keepalive, true);
  assert.match(newPlanId(), /^[0-9a-f]{32}$/);
  assert.notEqual(newPlanId(), newPlanId());
});

test("a pick sent now skips the debounce", async () => {
  const t = setup();
  t.scheduler.request(1, { now: true });
  await flush();
  assert.deepEqual(t.waiting.map((w) => w.plan), [1]);
});

// --- Go's early start -------------------------------------------------------------------------

test("the early start makes one request at a time, and the tap takes it once", async () => {
  let now = 0;
  let allowed = true;
  const sent: string[] = [];
  const answers: Array<(r: RouteResult) => void> = [];
  const early = new EarlyStart({ allowed: () => allowed, now: () => now });
  const send = (body: string) => () =>
    new Promise<RouteResult>((resolve) => {
      sent.push(body);
      answers.push(resolve);
    });
  assert.equal(early.start("a", send("a")), true);
  assert.equal(early.start("b", send("b")), false, "one in flight");
  // "b" waits for "a" (the next test); its tap takes it out of the wait.
  assert.equal(early.take("b"), null);
  assert.equal(early.busy(), true);
  answers[0]({ ok: true, route: FIRST });
  await flush();
  assert.equal(early.busy(), false);
  assert.equal(early.start("a", send("a")), false, "already asked for");
  assert.equal(early.take("b"), null);
  const taken = early.take("a");
  assert.ok(taken);
  assert.deepEqual(await taken, { ok: true, route: FIRST });
  assert.equal(early.take("a"), null, "taken once");
  allowed = false;
  assert.equal(early.start("c", send("c")), false, "not while Go is not shown, a ride is on or a route is asked for");
  allowed = true;
  now += 61_000;
  assert.equal(sent.length, 1);
});

test("the early start goes to the latest place asked for while one is in flight, once that settles (routing audit S4)", async () => {
  let allowed = true;
  const sent: string[] = [];
  const answers: Array<{ resolve: (r: RouteResult) => void; reject: (e: unknown) => void }> = [];
  const early = new EarlyStart({ allowed: () => allowed, now: () => 0, perMinute: 100 });
  const send = (body: string) => () =>
    new Promise<RouteResult>((resolve, reject) => {
      sent.push(body);
      answers.push({ resolve, reject });
    });
  // Typed on past "Union Market" to "Union Station": the last one wins, the one between is never asked for.
  assert.equal(early.start("market", send("market")), true);
  assert.equal(early.start("between", send("between")), false);
  assert.equal(early.start("station", send("station")), false);
  answers[0].resolve({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(sent, ["market", "station"]);
  assert.equal(early.busy(), true);
  answers[1].resolve({ ok: true, route: FIRST });
  const taken = early.take("station");
  assert.ok(taken);
  assert.deepEqual(await taken, { ok: true, route: FIRST });
  await flush();

  // A failed request still lets the waiting one go.
  assert.equal(early.start("x", send("x")), true);
  assert.equal(early.start("y", send("y")), false);
  answers[2].reject(new Error("network"));
  await flush();
  assert.deepEqual(sent.slice(2), ["x", "y"]);
  answers[3].resolve({ ok: true, route: FIRST });
  await flush();

  // The tap for the waiting place makes its own request: the wait is dropped, not sent as well.
  assert.equal(early.start("p", send("p")), true);
  assert.equal(early.start("q", send("q")), false);
  assert.equal(early.take("q"), null);
  answers[4].resolve({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(sent.slice(4), ["p"]);

  // Back to the place in flight: nothing newer waits.
  assert.equal(early.start("r", send("r")), true);
  assert.equal(early.start("s", send("s")), false);
  assert.equal(early.start("r", send("r")), false);
  answers[5].resolve({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(sent.slice(5), ["r"]);

  // No longer allowed when the one in flight settles (a tap's route asked for, Go left): the wait is dropped.
  assert.equal(early.start("u", send("u")), true);
  assert.equal(early.start("v", send("v")), false);
  allowed = false;
  answers[6].resolve({ ok: true, route: FIRST });
  await flush();
  allowed = true;
  assert.deepEqual(sent.slice(6), ["u"]);
  assert.equal(early.busy(), false);
});

test("a tap on another place, or the box cleared, drops the place waiting behind the one in flight (S4 review)", async () => {
  const sent: string[] = [];
  const answers: Array<(r: RouteResult) => void> = [];
  const early = new EarlyStart({ allowed: () => true, now: () => 0, perMinute: 100 });
  const send = (body: string) => () =>
    new Promise<RouteResult>((resolve) => {
      sent.push(body);
      answers.push(resolve);
    });
  // "station" waits behind "market"; the rider taps "plaza", which makes its own request.
  assert.equal(early.start("market", send("market")), true);
  assert.equal(early.start("station", send("station")), false);
  assert.equal(early.take("plaza"), null);
  answers[0]({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(sent, ["market"], "the wait for a place not chosen is never sent");
  // The box cleared while "y" waits behind "x": it is not sent either.
  assert.equal(early.start("x", send("x")), true);
  assert.equal(early.start("y", send("y")), false);
  early.forget();
  answers[1]({ ok: true, route: FIRST });
  await flush();
  assert.deepEqual(sent, ["market", "x"]);
  assert.equal(early.busy(), false);
});

test("App and PlaceSearch: the box cleared or emptied clears the settle timer and the wait (S4 review)", () => {
  assert.match(app, /const goEarlyToPlace = \(found: Place \| null\) => \{\s*window\.clearTimeout\(goEarlyTimer\.current\);\s*if \(!found\) \{\s*earlyStart\.current\?\.forget\(\);\s*return;\s*\}/);
  const search = readFileSync(new URL("../PlaceSearch.tsx", import.meta.url), "utf8");
  assert.match(search, /if \(top \|\| toldTop\.current\) onTopPlaceNow\.current\?\.\(top\);\s*toldTop\.current = top !== null;/);
});

test("App: a search result is asked for early once it stays the top result; Home at once (routing audit S4)", () => {
  assert.match(app, /goEarlyTimer\.current = window\.setTimeout\(\(\) => \{\s*goWarmFix\(\);\s*const point = placeFromSearch\(found, \(\) => undefined, entranceForPlace\);\s*if \(point\) goEarly\(point\);\s*\}, GO_EARLY_SETTLE_MS\);/);
  assert.match(app, /const GO_EARLY_SETTLE_MS = 400;/);
  // The tap clears it.
  assert.match(app, /const goToPlace = \(found: Place\) => \{\s*window\.clearTimeout\(goEarlyTimer\.current\);/);
});

test("the early start keeps inside its share of the API's per-minute count, and forgets what is stale", async () => {
  let now = 0;
  const early = new EarlyStart({ allowed: () => true, now: () => now, keepMs: 1000 });
  const done = () => Promise.resolve<RouteResult>({ ok: true, route: FIRST });
  let started = 0;
  for (let i = 0; i < EARLY_PER_MINUTE + 3; i += 1) {
    if (early.start(`p${i}`, done)) started += 1;
    await flush();
  }
  assert.equal(started, EARLY_PER_MINUTE);
  now += 2000;
  assert.equal(early.take(`p${EARLY_PER_MINUTE - 1}`), null, "past its keep");
  now += 60_000;
  assert.equal(early.start("later", done), true);
});

// --- App's wiring ------------------------------------------------------------------------------

const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");

test("App: Go asks for the first route, Plan keeps the full search on its Route button", () => {
  assert.match(app, /quick: mode === "go" && !riding,/);
  assert.match(app, /const asked = \{\s*confirmLong: plan\.confirmLong,\s*dials: plan\.dials,\s*vias: viaIndices\(plan\.points, VIA_MARKS\.isVia\),\s*straight: drawnLegs\(plan\.points\),\s*quick: plan\.quick,\s*follow,\s*followExact,\s*\};/);
  // The full plan follows only a first route, and is asked for without quick.
  assert.match(app, /refine: \(plan: Plan, shown: RouteResult, planId: string\) =>\s*shown\.ok && shown\.route\.provisional/);
});

test("App: the better route is taken before Start only, said once, and moves no focus", () => {
  const start = app.indexOf("onRefined: (plan: Plan, result: RouteResult) => {");
  const end = app.indexOf("    });\n  }", start);
  const body = app.slice(start, end);
  assert.ok(start > 0 && end > start);
  assert.match(body, /takesRefined\(now\.answer, now\.riding\)/);
  assert.match(body, /betterRouteSaid\(now\.answer, result\.route\)/);
  assert.match(body, /setNoticeSaying\(line, line\)/);
  assert.doesNotMatch(body, /focus\(/);
  // The route's own sentence is held, so the swap is not read out twice.
  assert.match(app, /const routeSaid = refinedHeld && answer === refinedHeld\.route \? refinedHeld\.said : settledSaid;/);
});

test("App: Go starts routing early, to the top result and to Home, through one early start", () => {
  assert.match(app, /onTopPlace=\{goEarlyToPlace\}/);
  assert.match(app, /goStart\.kind === "here" && homeEarly\) goEarly\(homeEarly\)/);
  // Review F14: a Home kept on this device signed out is asked for early too.
  assert.match(app, /const homeEarly = myGo\.home !== null \? myGo\.home\.point : null;/);
  assert.match(app, /const early = earlyStart\.current\?\.take\(routeRequestBody\(plan\.points, plan\.preset, asked\)\) \?\? null;/);
  assert.match(app, /allowed: \(\) => modeRef\.current === "go" && !shownNow\.current\.riding && !scheduler\.current\?\.busy\(\)/);
  // A destination picked is asked for at once.
  assert.match(app, /\}, \{ now: now \|\| \(goPickedNow\.current && mode === "go"\) \}\);/);
});

test("App: Go's controls are unchanged: no new button or field for any of it", () => {
  const go = readFileSync(new URL("../app/Go.tsx", import.meta.url), "utf8");
  // 18: v0.7.0's places stream added Go's More chip with Repair and Sights behind it, and Plan's
  // map chip for Places to see (PlanMapChips lives in Go.tsx); faster routing added none.
  // 21 and 4 since "Setting Home simply" (lib/homeSet.ts): the Home sheet (HomeSetter, Go's and Settings') has
  // Pick on the map, Clear Home and the Home search (which moved here from Settings), and More has Change Home.
  // None is on Go until asked for: the sheet opens from the Home chip, Change Home is behind More
  // (lib/homeSet.test.ts holds Go's always-shown row at five chips).
  // The edit-route redesign (Stephen 2026-10-18): one more, the route card's button (Edit route); Add a stop stays.
  // Go's bar mirroring Plan's (Stephen 2026-10-18: "mirror what plan does in general, but instead of route, we start
  // the ride"): three more, Undo, Redo and the big Start ride / Route, beside the Clear that was the destination's X.
  // Metro behind More (Stephen 2026-10-19: "Metro stops should be on the list in more"): one more, still behind More.
  // Plan's map chips behind one Find chip (Stephen 2026-10-21: "It's more room"): one more, Find, in Plan only.
  // Favorite places (Stephen 2026-10-26, lib/favoritePlaces.ts): signed in, the Favorites chip in the Home chip's place
  // (one more tag, never both shown) and its popout's ten buttons (Home, Work and a place, each with its Edit button;
  // the two Set rows; Add a place and Edit) and one search field, none on Go until the chip is tapped.
  // Saved routes behind More (Stephen 2026-10-26: "Add saved routes in the more part of the go tab"): one more, still behind More.
  // The owner's P1 (2026-10-28): two more, each folding what was always shown behind one press: "+ Add a stop", which
  // opens its field, and New destination, under a route, which opens Where to? and the place chips.
  assert.equal((go.match(/<button/g) ?? []).length, 41, "the same buttons as before, the Home sheet's, the route card's, Go's bar, More's Metro and Saved routes, Plan's Find, Favorites', Add a stop's and New destination");
  assert.equal((go.match(/<PlaceSearch/g) ?? []).length, 5, "the same search fields as before, the Home sheet's and Favorites'");
});
