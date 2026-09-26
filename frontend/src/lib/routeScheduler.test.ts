import { test } from "node:test";
import assert from "node:assert/strict";
import { DEBOUNCE_MS, RouteScheduler, type SchedulerState, type Timers } from "./routeScheduler.ts";
import { describeError, type RouteResponse, type RouteResult } from "./api.ts";

/** A clock the test moves by hand. */
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
      const due = [...this.pending.entries()]
        .filter(([, t]) => t.at <= until)
        .sort((a, b) => a[1].at - b[1].at)[0];
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
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

const ROUTE = { distance_m: 1 } as RouteResponse;

/** A fake API: each call waits for the test to answer it. */
function fakeApi() {
  const calls: Array<{ plan: number; answer: (r: RouteResult) => void }> = [];
  let inFlight = 0;
  let maxInFlight = 0;
  const send = (plan: number) =>
    new Promise<RouteResult>((resolve) => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      calls.push({
        plan,
        answer: (r) => {
          inFlight -= 1;
          resolve(r);
        },
      });
    });
  return { calls, send, maxInFlight: () => maxInFlight };
}

function setup() {
  const timers = new FakeTimers();
  const api = fakeApi();
  const shown: Array<{ plan: number; result: RouteResult }> = [];
  const states: SchedulerState[] = [];
  const scheduler = new RouteScheduler<number>({
    send: api.send,
    onResult: (plan, result) => shown.push({ plan, result }),
    onState: (s) => states.push(s),
    timers,
  });
  return { timers, api, shown, states, scheduler };
}

const ok: RouteResult = { ok: true, route: ROUTE };

test("a burst of changes inside the debounce is one request, for the last plan", async () => {
  const { timers, api, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(100);
  scheduler.request(2);
  await timers.advance(100);
  scheduler.request(3);
  await timers.advance(DEBOUNCE_MS - 1);
  assert.equal(api.calls.length, 0);
  await timers.advance(1);
  assert.deepEqual(
    api.calls.map((c) => c.plan),
    [3],
  );
});

test("four clicks half a second apart end routed on the last plan, one request at a time", async () => {
  // The correctness reviewer's probe: start, end and two vias at 0.5 s, with
  // each request taking 1.2 s. The old planner had three in flight and the
  // API's per-client slots refused the last with "Slow down".
  const timers = new FakeTimers();
  let inFlight = 0;
  let maxInFlight = 0;
  const sent: number[] = [];
  const shown: Array<{ plan: number; result: RouteResult }> = [];
  const scheduler = new RouteScheduler<number>({
    send: (plan) =>
      new Promise((resolve) => {
        sent.push(plan);
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        timers.set(() => {
          inFlight -= 1;
          // Like the API: a third concurrent request would be refused.
          resolve(inFlight >= 2 ? { ok: false, error: describeError(429, null, "2") } : ok);
        }, 1200);
      }),
    onResult: (plan, result) => shown.push({ plan, result }),
    timers,
  });
  for (const plan of [1, 2, 3, 4]) {
    scheduler.request(plan);
    await timers.advance(500);
  }
  await timers.advance(20_000);
  assert.equal(maxInFlight, 1, `${maxInFlight} requests were in flight at once`);
  assert.equal(shown.length, 1);
  assert.equal(shown[0].plan, 4);
  assert.equal(shown[0].result.ok, true);
  assert.ok(sent.length <= 3, `sent ${sent.join(",")}`);
});

test("an in-flight request is not abandoned: the next waits for it to finish", async () => {
  const { timers, api, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  scheduler.request(2);
  await timers.advance(DEBOUNCE_MS * 10);
  assert.equal(api.calls.length, 1, "a second request went while the first held its slot");
  api.calls[0].answer(ok);
  await flush();
  assert.equal(api.calls.length, 2);
  assert.equal(api.calls[1].plan, 2);
});

test("a 429 with Retry-After is waited out for exactly that long, then the latest plan goes", async () => {
  const { timers, api, shown, states, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, error: describeError(429, { error: "slow" }, "7") });
  await flush();
  assert.deepEqual(states.at(-1), { kind: "waiting", seconds: 7 });
  assert.equal(shown.length, 0, "the refusal was shown instead of waited out");
  scheduler.request(2); // the rider keeps editing while we wait
  await timers.advance(6999);
  assert.equal(api.calls.length, 1, "resent before Retry-After was up");
  await timers.advance(1);
  assert.equal(api.calls.length, 2);
  assert.equal(api.calls[1].plan, 2);
  api.calls[1].answer(ok);
  await flush();
  assert.deepEqual(
    shown.map((s) => [s.plan, s.result.ok]),
    [[2, true]],
  );
});

test("a 503 with Retry-After is waited out too", async () => {
  const { timers, api, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, error: describeError(503, null, "30") });
  await flush();
  await timers.advance(29_999);
  assert.equal(api.calls.length, 1);
  await timers.advance(1);
  assert.equal(api.calls.length, 2);
});

test("the waits are bounded, and then the refusal is shown", async () => {
  const { timers, api, shown, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  for (let i = 0; i < 10 && shown.length === 0; i += 1) {
    api.calls.at(-1)?.answer({ ok: false, error: describeError(429, null, "2") });
    await flush();
    await timers.advance(2000);
  }
  assert.equal(shown.length, 1);
  assert.equal(shown[0].result.ok, false);
  assert.ok(api.calls.length <= 4, `${api.calls.length} requests for one refused plan`);
});

test("a refusal without Retry-After is shown at once, not retried on a timer", async () => {
  const { timers, api, shown, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, error: describeError(429, null, null) });
  await flush();
  await timers.advance(60_000);
  assert.equal(api.calls.length, 1);
  assert.equal(shown.length, 1);
});

test("clearing drops the pending plan and hides a late answer", async () => {
  const { timers, api, shown, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  scheduler.clear();
  api.calls[0].answer(ok);
  await flush();
  await timers.advance(10_000);
  assert.equal(shown.length, 0);
  assert.equal(api.calls.length, 1);
});

test("an answer for the current plan is shown once", async () => {
  const { timers, api, shown, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  api.calls[0].answer(ok);
  await flush();
  assert.equal(shown.length, 1);
  await timers.advance(10_000);
  assert.equal(api.calls.length, 1);
});

test("a change made while a request is out still waits its debounce after the answer", async () => {
  const { timers, api, scheduler } = setup();
  scheduler.request(1);
  await timers.advance(DEBOUNCE_MS);
  scheduler.request(2);
  await timers.advance(50);
  api.calls[0].answer(ok); // the slot frees before plan 2's debounce is up
  await flush();
  assert.equal(api.calls.length, 1, "plan 2 went before its debounce");
  await timers.advance(DEBOUNCE_MS);
  assert.equal(api.calls.length, 2);
  assert.equal(api.calls[1].plan, 2);
});
