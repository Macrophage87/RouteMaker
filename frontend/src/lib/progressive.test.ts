/**
 * v0.7.0, "Faster routing, mainly for Go": Go's first route then its full plan (lib/progressive.ts and the scheduler's
 * `refine`), Go's early start, and how App wires them (one line said once, no focus moved, never mid-ride).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { betterRouteSaid, CALMER_BY_M, EarlyStart, EARLY_PER_MINUTE, sameRoute, takesRefined } from "./progressive.ts";
import { RouteScheduler, type SchedulerState, type Timers } from "./routeScheduler.ts";
import { describeError, routeRequestBody, type RouteResponse, type RouteResult } from "./api.ts";
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
  assert.match(app, /refine: \(plan: Plan, shown: RouteResult\) =>\s*shown\.ok && shown\.route\.provisional/);
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
  assert.match(app, /\}, \{ now: goPickedNow\.current && mode === "go" \}\);/);
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
  assert.equal((go.match(/<button/g) ?? []).length, 38, "the same buttons as before, the Home sheet's, the route card's, Go's bar, More's Metro, Plan's Find and Favorites'");
  assert.equal((go.match(/<PlaceSearch/g) ?? []).length, 5, "the same search fields as before, the Home sheet's and Favorites'");
});
