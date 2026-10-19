/** Go's More direct and Calmer (lib/neighbours.ts; the owner, 2026-10-16). */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { describeError, requestNeighbours, type DescriptionEntry, type NeighbourOption, type RouteResponse, type RouteResult } from "./api.ts";
import { candidateFieldset } from "./candidatePicker.ts";
import { announceHow, candidateRoute, candidateRows, candidatesHint, NEIGHBOURS_HINT, YOUR_SETTING } from "./candidates.ts";
import { startDials } from "./dials.ts";
import {
  differsEnough,
  displacedBy,
  keptNeighbours,
  MAX_ROWS,
  MIN_MOVED_M,
  movedBetweenTiers,
  neighbourDials,
  neighboursSaid,
  offersNeighbours,
  rideDials,
  tradeoffLine,
  withNeighbours,
} from "./neighbours.ts";
import { RouteScheduler, type Timers } from "./routeScheduler.ts";
import { announceRoute } from "./summary.ts";

const MILE = 1609.344;

function route(over: Partial<RouteResponse> & { s?: [number, number, number, number] } = {}): RouteResponse {
  const [one, two, three, four] = over.s ?? [3000, 2000, 1000, 0];
  return {
    preset: "default",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [] },
    distance_m: one + two + three + four,
    duration_s: 1800,
    climb_m: 20,
    descent_m: 20,
    stress_m: { "1": one, "2": two, "3": three, "4": four },
    attribution: [],
    ...over,
  } as RouteResponse;
}

function option(kind: "direct" | "calmer", r: RouteResponse, stress = kind === "direct" ? 40 : 80): NeighbourOption {
  return { kind, stress, route: r };
}

function stretch(street: string, from: number, to: number): DescriptionEntry {
  return { kind: "stretch", from_m: from, to_m: to, from_mi: from / MILE, to_mi: to / MILE, street, tier: 1, facility: "path", turn: null };
}

const OWN = route();
// 4 min faster, 0.6 mi more on LTS 3.
const DIRECT = route({ duration_s: 1800 - 240, s: [3000, 2000 - 966, 1000 + 966, 0] });

test("the tradeoff says what is gained first, then the cost, miles first and kilometres in brackets", () => {
  assert.equal(tradeoffLine(OWN, DIRECT), "4 min faster, 0.6 mi (1.0 km) more on busier streets");
  const calmer = route({ duration_s: 1980, s: [4448, 2000, 0, 0] });
  assert.equal(tradeoffLine(OWN, calmer), "0.6 mi (1.0 km) less on busy streets, 3 min longer");
  const lts4 = route({ duration_s: 1500, s: [2000, 2000, 1000, 1000] });
  assert.equal(tradeoffLine(OWN, lts4), "5 min faster, 0.6 mi (1.0 km) more on heavy-traffic roads");
  const both = route({ duration_s: 1500, s: [1000, 2000, 2000, 1000] });
  assert.equal(tradeoffLine(OWN, both), "5 min faster, 1.2 mi (2.0 km) more on heavy-traffic roads");
  // Rider-facing words name no stress level by number (the review's 8).
  for (const r of [DIRECT, lts4, both, calmer]) assert.doesNotMatch(tradeoffLine(OWN, r), /LTS/);
});

test("each option must do what its name says: More direct saves a minute, Calmer takes busy riding off", () => {
  // A "more direct" route that is no faster, though it differs: not offered.
  const notFaster = route({ duration_s: 1790, s: [2000, 1000, 3000, 0] });
  assert.deepEqual(keptNeighbours(OWN, [option("direct", notFaster)], "default"), []);
  // A "calmer" route that is quicker but no calmer: not offered as Calmer.
  const notCalmer = route({ duration_s: 1500, s: [3000, 2000, 1000, 0] });
  assert.deepEqual(keptNeighbours(OWN, [option("calmer", notCalmer)], "default"), []);
});

test("an option the same as one of the routes to choose from is dropped, and the choice holds at most 4 rows", () => {
  const answer = { ...OWN, candidates: [{ ...DIRECT }] };
  assert.deepEqual(keptNeighbours(answer, [option("direct", DIRECT)], "default"), [], "already in the choice");
  const calmer = route({ duration_s: 1980, s: [4448, 2000, 0, 0] });
  const both = [option("direct", DIRECT), option("calmer", calmer)];
  const [r2, r3, r4] = [route({ duration_s: 2400 }), route({ duration_s: 2600 }), route({ duration_s: 2800 })];
  // The owner, 2026-10-19 ("I never see the options"): a full choice makes room for them, from its last routes.
  const four = { ...OWN, candidates: [r2, r3, r4] };
  const kept = keptNeighbours(four, both, "default");
  assert.deepEqual(kept.map((r) => r.neighbour?.kind), ["direct", "calmer"], "four already: both still offered");
  const picked = withNeighbours(four, kept);
  assert.equal(picked?.candidates?.length, MAX_ROWS - 1);
  assert.deepEqual(picked?.candidates?.slice(0, 1), [r2], "the router's first other route stays, the last two give way");
  // A route the rider has already chosen stays where it is, and the rows before it: only what is left goes to them.
  const chosenThird = keptNeighbours(four, both, "default", undefined, 2);
  assert.deepEqual(chosenThird.map((r) => r.neighbour?.kind), ["direct"]);
  assert.deepEqual(withNeighbours(four, chosenThird)?.candidates?.slice(0, 2), [r2, r3]);
  assert.deepEqual(keptNeighbours(four, both, "default", undefined, 3), [], "the last chosen: nothing gives way");
  const chosenSecond = keptNeighbours(four, both, "default", undefined, 1);
  assert.deepEqual(chosenSecond.map((r) => r.neighbour?.kind), ["direct", "calmer"]);
  assert.deepEqual(withNeighbours(four, chosenSecond)?.candidates?.slice(0, 1), [r2]);
  // Two routes of its own and both options: one gives way. Said as such, the count heard before being out of date.
  const three = { ...OWN, candidates: [r2, r3] };
  const keptThree = keptNeighbours(three, both, "default");
  const pickedThree = withNeighbours(three, keptThree);
  assert.deepEqual(pickedThree?.candidates?.slice(0, 1), [r2]);
  assert.equal(displacedBy(three, pickedThree, keptThree), 1);
  assert.equal(neighboursSaid(keptThree, 1), "More direct and Calmer replace the last route.");
  assert.equal(displacedBy(four, picked, kept), 2);
  assert.equal(neighboursSaid(kept, 2), "More direct and Calmer replace the last 2 routes.");
  assert.equal(neighboursSaid(kept.slice(1), 1), "Calmer replaces the last route.");
  assert.equal(displacedBy(OWN, withNeighbours(OWN, keptThree), keptThree), 0, "room for them: none gives way");
});

test("a route that gains nothing has no line, and is not offered", () => {
  const worse = route({ duration_s: 2100, s: [2000, 2000, 2000, 0] });
  assert.equal(tradeoffLine(OWN, worse), "");
  assert.deepEqual(keptNeighbours(OWN, [option("direct", worse)], "default"), []);
});

test("a notable trail gained or left is named in the same line", () => {
  const own = route({ description: [stretch("Metropolitan Branch Trail", 0, 2000)] });
  const direct = { ...DIRECT, description: [] };
  assert.equal(tradeoffLine(own, direct), "4 min faster, 0.6 mi (1.0 km) more on busier streets, leaves the Metropolitan Branch Trail");
  const calmer = route({ duration_s: 1980, s: [4448, 2000, 0, 0], description: [stretch("the Capital Crescent Trail", 0, 1500)] });
  assert.equal(tradeoffLine(OWN, calmer), "0.6 mi (1.0 km) less on busy streets, on the Capital Crescent Trail, 3 min longer");
});

test("an option is offered only where it really differs: 2 min, or 0.3 mi (0.5 km) moved between tiers", () => {
  assert.equal(differsEnough(OWN, OWN), false, "the same line is dropped");
  // A minute and a tenth of a mile moved: a near-duplicate.
  const near = route({ duration_s: 1740, s: [3000, 1840, 1160, 0] });
  assert.equal(differsEnough(OWN, near), false);
  assert.deepEqual(keptNeighbours(OWN, [option("direct", near)], "default"), []);
  assert.equal(differsEnough(OWN, route({ duration_s: 1800 - 120 })), true, "two minutes is enough");
  const moved = route({ s: [3000, 2000 - MIN_MOVED_M, 1000 + MIN_MOVED_M, 0], duration_s: 1770 });
  assert.equal(movedBetweenTiers(OWN, moved), MIN_MOVED_M);
  assert.equal(differsEnough(OWN, moved), true, "0.3 mi moved is enough");
});

test("both kept in order, more direct first, each tagged with its setting and line; a second the same as the first is dropped", () => {
  const calmer = route({ duration_s: 1980, s: [4448, 2000, 0, 0] });
  const kept = keptNeighbours(OWN, [option("calmer", calmer), option("direct", DIRECT)], "default");
  assert.deepEqual(kept.map((r) => [r.neighbour?.kind, r.neighbour?.stress]), [["direct", 40], ["calmer", 80]]);
  const twins = keptNeighbours(OWN, [option("direct", DIRECT), option("calmer", { ...DIRECT })], "default");
  assert.deepEqual(twins.map((r) => r.neighbour?.kind), ["direct"]);
});

test("Novice and Nervous, and Cargo with passengers, are never offered more LTS 4 to be more direct", () => {
  const onto4 = route({ duration_s: 1500, s: [2000, 2000, 1000, 1000] });
  assert.equal(keptNeighbours(OWN, [option("direct", onto4, 90)], "novice").length, 0);
  assert.equal(keptNeighbours(OWN, [option("direct", onto4, 70)], "cargo", { carrying: "people" }).length, 0);
  assert.equal(keptNeighbours(OWN, [option("direct", onto4, 70)], "cargo", { carrying: "cargo" }).length, 1);
  assert.equal(keptNeighbours(OWN, [option("direct", DIRECT, 90)], "novice").length, 1, "more LTS 3 is still a choice");
});

test("bike-only ride types and plain Bikeshare ask; not the multimodal trips, Rebalance Ride or Mass Ride", () => {
  for (const preset of ["default", "novice", "fast", "bikeshare"] as const) assert.equal(offersNeighbours(preset), true, preset);
  for (const preset of ["rebalance", "bike-transit", "bikeshare-transit", "mass-ride"] as const) {
    assert.equal(offersNeighbours(preset), false, preset);
  }
});

test("Bikeshare asks with its own docks, so only the ride between them changes; a free e-bike's plan does not ask", () => {
  const dials = startDials("bikeshare");
  const stop = (kind: "dock" | "free_bike" | "outside_dock", id: string | null) =>
    ({ kind, name: "x", lon: 0, lat: 0, station_id: id, availability: "known", bikes_available: 1, docks_available: 1 }) as const;
  const plan = (start: ReturnType<typeof stop>, end: ReturnType<typeof stop>, ending: "dock" | "outside_dock" = "dock") =>
    route({ preset: "bikeshare", bikeshare: { bike: "classic", ending, start, end } as unknown as RouteResponse["bikeshare"] });
  const asked = neighbourDials("bikeshare", dials, plan(stop("dock", "a"), stop("dock", "b")));
  assert.ok(asked);
  assert.equal(asked.pickupStation, "a");
  assert.equal(asked.dropoffStation, "b");
  assert.equal(asked.stress, dials.stress, "the rider's own setting: the API moves it a notch");
  const outside = neighbourDials("bikeshare", dials, plan(stop("dock", "a"), stop("outside_dock", null), "outside_dock"));
  assert.equal(outside?.pickupStation, "a");
  assert.equal(outside?.dropoffStation, undefined);
  assert.equal(neighbourDials("bikeshare", dials, plan(stop("free_bike", null), stop("dock", "b"))), null);
  const own = startDials("default");
  assert.equal(neighbourDials("default", own, OWN), own, "other ride types ask with the plan's own dials");
});

test("Go's route choice: the rider's own first, then More direct and Calmer, each one short line", () => {
  const kept = keptNeighbours(OWN, [option("direct", DIRECT), option("calmer", route({ duration_s: 1980, s: [4448, 2000, 0, 0] }))], "default");
  const picked = withNeighbours(OWN, kept);
  const rows = candidateRows(picked);
  assert.ok(rows);
  assert.equal(rows[0].name, `${YOUR_SETTING} 3.7 mi (6.0 km)`);
  assert.deepEqual(rows.slice(1), [
    { name: "More direct", line: "4 min faster, 0.6 mi (1.0 km) more on busier streets" },
    { name: "Calmer", line: "0.6 mi (1.0 km) less on busy streets, 3 min longer" },
  ]);
  assert.equal(candidatesHint(picked), `${NEIGHBOURS_HINT} The map shows the one chosen, and the route description below follows it.`);
  // The same radio group the routes to choose from use, the rider's own checked.
  const html = renderToStaticMarkup(candidateFieldset("p", { answer: picked, choice: 0, onChoose: () => {} }));
  assert.equal((html.match(/type="radio"/g) ?? []).length, 3);
  assert.match(html, /aria-describedby="p-line-0" name="p-candidate" checked=""/);
  // No options: no picker.
  assert.equal(candidateRows(withNeighbours(OWN, [])), null);
});

test("calm candidates keep their names, with More direct after them", () => {
  const answer = { ...OWN, candidates: [route({ distance_m: 7000, duration_s: 2400 })] };
  const picked = withNeighbours(answer, keptNeighbours(answer, [option("direct", DIRECT, 90)], "trailmaxxing"));
  const rows = candidateRows(picked) ?? [];
  assert.match(rows[0].name, /^Route 1/);
  assert.match(rows[1].name, /^Route 2:/);
  assert.equal(rows[2].name, "More direct");
  assert.match(candidatesHint(picked), /^Each is about as calm as the first\. More direct and Calmer/);
});

test("said once on arrival in a short line, and a choice is said by its name", () => {
  const kept = keptNeighbours(OWN, [option("direct", DIRECT), option("calmer", route({ duration_s: 1980, s: [4448, 2000, 0, 0] }))], "default");
  assert.equal(neighboursSaid(kept), "More direct and Calmer added to the route choice.");
  assert.equal(neighboursSaid(kept.slice(1)), "Calmer added to the route choice.");
  assert.equal(neighboursSaid([]), "");
  const picked = withNeighbours(OWN, kept);
  assert.deepEqual(announceHow(picked, 2, true), { chosen: { rank: 3, of: 3, name: "Calmer" } });
  assert.match(announceRoute(candidateRoute(picked, 2)!, [], announceHow(picked, 2, true)), /^Calmer route chosen: /);
  // The answer's own arrival sentence does not change when they come: it is said from the answer, not the picked list.
  assert.deepEqual(announceHow(OWN, 0, false), {});
});

test("choosing one rides it and changes no setting: the plan's dials and the saved default are untouched", () => {
  const dials = startDials("default");
  const before = JSON.stringify(dials);
  const kept = keptNeighbours(OWN, [option("calmer", route({ duration_s: 1980, s: [4448, 2000, 0, 0] }), 80)], "default");
  const picked = withNeighbours(OWN, kept);
  const shown = candidateRoute(picked, 1);
  const ride = rideDials(dials, shown);
  assert.equal(ride.stress, 80, "the ride re-routes at the option's own setting");
  assert.notEqual(ride, dials);
  assert.equal(JSON.stringify(dials), before, "the plan's dials are not changed");
  assert.equal(rideDials(dials, OWN), dials, "the rider's own route rides the plan's dials");
  assert.equal(OWN.candidates, undefined, "the answer itself is not changed");
  // App: choosing sets only the choice; nothing it calls writes a setting or the saved default.
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const choose = app.slice(app.indexOf("const choose = useCallback("), app.indexOf("}, []);", app.indexOf("const choose = useCallback(")));
  assert.doesNotMatch(choose, /setDials|saveSettings|setDefault/);
  assert.match(app, /dials: rideDials\(planDials, rest \? null : route\)/);
});

test("one request for both, with the plan's own body (so the route cache and one count of the limit serve it)", async () => {
  const sent: { url: string; body: string }[] = [];
  const fetchImpl = async (url: string, init: RequestInit) => {
    sent.push({ url, body: String(init.body) });
    return new Response(JSON.stringify({ stress: 70, options: [option("direct", DIRECT), { kind: "nope", stress: 1, route: DIRECT }] }), { status: 200 });
  };
  const result = await requestNeighbours([[-77, 38.9], [-77.01, 38.91]], "default", { dials: startDials("default"), fetchImpl });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, "/api/route/neighbours");
  const body = JSON.parse(sent[0].body);
  assert.equal(body.stress, 70);
  assert.equal(body.quick, undefined);
  assert.ok(result.ok && result.options.length === 1, "an option that is not one is left out");
  const refused = await requestNeighbours([[-77, 38.9], [-77.01, 38.91]], "default", {
    fetchImpl: async () => new Response(JSON.stringify({ error: "busy" }), { status: 429, headers: { "Retry-After": "2" } }),
  });
  assert.ok(!refused.ok && refused.error.retryAfterS === 2);
});

// --- The scheduler: the request after a final route ----------------------------------------------

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

type After = { ok: true; options: NeighbourOption[] } | { ok: false; error: ReturnType<typeof describeError> };

function setup() {
  const timers = new FakeTimers();
  const waiting: Array<{ kind: string; plan: number; answer: (r: RouteResult | After) => void }> = [];
  let inFlight = 0;
  let most = 0;
  const call = <R>(kind: string, plan: number) =>
    new Promise<R>((resolve) => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      waiting.push({ kind, plan, answer: (r) => ((inFlight -= 1), resolve(r as R)) });
    });
  const shown: number[] = [];
  const after: Array<{ plan: number; result: After }> = [];
  const states: string[] = [];
  const scheduler = new RouteScheduler<number, After>({
    send: (plan) => call<RouteResult>("send", plan),
    refine: (plan, first) => (first.ok && first.route.provisional ? () => call<RouteResult>("refine", plan) : null),
    onResult: (plan) => shown.push(plan),
    onRefined: () => {},
    after: (plan, final) => (final.ok && !final.route.provisional ? () => call<After>("after", plan) : null),
    onAfter: (plan, result) => after.push({ plan, result }),
    onState: (s) => states.push(s.kind),
    timers,
  });
  return { timers, waiting, shown, after, states, scheduler, most: () => most };
}

const FIRST = { ...OWN, provisional: true };
const FULL = { ...OWN, provisional: false };

test("the options are asked for after the full plan, never as the request in flight, and the route is not shown as loading", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FIRST });
  await flush();
  t.waiting[1].answer({ ok: true, route: FULL });
  await flush();
  assert.deepEqual(t.waiting.map((w) => w.kind), ["send", "refine", "after"]);
  assert.equal(t.states.at(-1), "idle", "the route stands: nothing says planning");
  assert.equal(t.scheduler.busy(), false, "nothing waits for them");
  t.waiting[2].answer({ ok: true, options: [] });
  await flush();
  assert.deepEqual(t.after.map((a) => a.plan), [1]);
});

test("a full answer at once is followed by the options directly", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FULL });
  await flush();
  assert.deepEqual(t.waiting.map((w) => w.kind), ["send", "after"]);
});

test("a new plan while the options compute is sent at once, and their late answer is dropped", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FULL });
  await flush();
  t.scheduler.request(2);
  await t.timers.advance(300);
  assert.deepEqual(t.waiting.map((w) => [w.kind, w.plan]), [["send", 1], ["after", 1], ["send", 2]], "not held behind them");
  t.waiting[1].answer({ ok: true, options: [] });
  await flush();
  assert.deepEqual(t.after, [], "the options of a plan no longer asked for are not given");
});

test("Start pressed while the options compute: the ride's re-route goes at once", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FULL });
  await flush();
  assert.equal(t.waiting.at(-1)?.kind, "after");
  // The ride starts and soon re-routes (Ride mode sends its re-plans at once).
  t.scheduler.request(2, { now: true });
  await flush();
  assert.deepEqual(t.waiting.at(-1), { ...t.waiting.at(-1), kind: "send", plan: 2 }, "sent without waiting");
  t.waiting.at(-1)!.answer({ ok: true, route: FULL });
  await flush();
  assert.deepEqual(t.shown, [1, 2]);
  t.waiting[1].answer({ ok: true, options: [] });
  await flush();
  assert.equal(t.after.some((a) => a.plan === 1), false);
});

test("a refused options request holds nothing back: the next plan goes at once", async () => {
  const t = setup();
  t.scheduler.request(1);
  await t.timers.advance(300);
  t.waiting[0].answer({ ok: true, route: FULL });
  await flush();
  t.waiting[1].answer({ ok: false, error: describeError(503, null, "5") });
  await flush();
  assert.deepEqual(t.shown, [1]);
  t.scheduler.request(2);
  await t.timers.advance(300);
  assert.equal(t.waiting.length, 3, "no Retry-After hold from the options");
  assert.equal(t.states.includes("waiting"), false);
});

test("App: asked for in Go only, before Start, on the ride types that offer them; said once by their own line", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const start = app.indexOf("after: (plan: Plan, final: RouteResult) => {");
  const body = app.slice(start, app.indexOf("onAfter:", start));
  assert.ok(start > 0);
  assert.match(body, /modeRef\.current !== "go" \|\| now\.riding \|\| now\.startAsked/);
  assert.match(body, /!offersNeighbours\(plan\.preset\) \|\| plan\.confirmLong/);
  assert.match(app, /announce\(neighboursSaid\(kept, displacedBy\(answer, picked, kept\)\)\)/);
  // The routes kept in place are the answer's own: the rider's choice, held to their count, and kept for the same answer.
  assert.match(app, /before\.answer === answer \? before\.keepRouter : Math\.min\(now\.choice, answer\.candidates\?\.length \?\? 0\)/);
  // Ride mode starts with no options asked for: Start pressed or a ride on, none are.
  assert.match(app.slice(app.indexOf("onAfter:")), /now\.riding\) return;/);
  // The route's own sentence is the answer's, so it is not read again when they come.
  assert.match(app, /chosen \? announceHow\(picked, choice, true\) : announceHow\(answer, choice, false\)/);
  // Shown in the existing choice: the route section gets the answer with them.
  assert.match(app, /answer: picked, choice,/);
});
