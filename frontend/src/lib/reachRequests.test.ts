// Reach's requests, named as Go's plans: one the sheet gives up on is stopped on the server, so it frees the rider's
// routing slot, and a busy answer is asked again once after its Retry-After.
import assert from "node:assert/strict";
import test from "node:test";
import { ReachRequests, requestReach } from "./reach.ts";

const ANSWER = { preset: "default", minutes: [15], direction: "from", combine: "any", stress_used: 40, groups: [], calm: null, unplaced: [] };

type Sent = { url: string; headers: Record<string, string> };

function recorder(answers: Array<() => Response | Promise<Response>>) {
  const sent: Sent[] = [];
  const fetchImpl = async (url: string, init: RequestInit) => {
    sent.push({ url, headers: { ...(init.headers as Record<string, string>) } });
    const next = answers.shift();
    assert.ok(next, "no more answers");
    return next();
  };
  return { sent, fetchImpl };
}

function ids() {
  let n = 0;
  return () => `plan${String((n += 1)).padStart(8, "0")}`;
}

test("each Reach request names itself", async () => {
  const { sent, fetchImpl } = recorder([() => new Response(JSON.stringify(ANSWER), { status: 200 })]);
  const requests = new ReachRequests({ fetchImpl, planId: ids(), cancel: () => assert.fail("nothing to cancel") });
  const result = await requests.ask({});
  assert.ok(result.ok);
  assert.equal(sent[0].headers["X-Plan-Id"], "plan00000001");
  assert.equal(sent[0].headers["X-Plan-Replaces"], undefined);
});

test("a Reach request the sheet gives up on is cancelled, and the next one names it", async () => {
  let release: (r: Response) => void = () => {};
  const { sent, fetchImpl } = recorder([
    () => new Promise<Response>((resolve) => (release = resolve)),
    () => new Response(JSON.stringify(ANSWER), { status: 200 }),
  ]);
  const cancelled: string[] = [];
  const requests = new ReachRequests({ fetchImpl, planId: ids(), cancel: (id) => cancelled.push(id) });
  const abort = new AbortController();
  const first = requests.ask({}, abort.signal);
  await Promise.resolve();
  abort.abort();
  requests.drop();
  assert.deepEqual(cancelled, ["plan00000001"]);
  const second = await requests.ask({});
  assert.ok(second.ok);
  assert.equal(sent[1].headers["X-Plan-Id"], "plan00000002");
  assert.equal(sent[1].headers["X-Plan-Replaces"], "plan00000001");
  release(new Response("{}", { status: 409 }));
  await first;
  // Answered, nothing is in flight: a later drop (the sheet closing) sends nothing.
  requests.drop();
  assert.deepEqual(cancelled, ["plan00000001"]);
});

test("a busy Reach answer is asked again once after its Retry-After", async () => {
  const { sent, fetchImpl } = recorder([
    () => new Response("{}", { status: 429, headers: { "Retry-After": "2" } }),
    () => new Response(JSON.stringify(ANSWER), { status: 200 }),
  ]);
  const waited: number[] = [];
  const requests = new ReachRequests({ fetchImpl, planId: ids(), wait: async (ms) => void waited.push(ms) });
  const result = await requests.ask({});
  assert.ok(result.ok);
  assert.deepEqual(waited, [2000]);
  assert.equal(sent.length, 2);
});

test("a busy Reach answer with a long or no Retry-After is said, not asked again", async () => {
  for (const headers of [{ "Retry-After": "60" }, {} as Record<string, string>]) {
    const { sent, fetchImpl } = recorder([() => new Response("{}", { status: 503, headers })]);
    const requests = new ReachRequests({ fetchImpl, planId: ids(), wait: async () => assert.fail("no wait") });
    const result = await requests.ask({});
    assert.ok(!result.ok && /busy/.test(result.message));
    assert.equal(sent.length, 1);
  }
  const said = await requestReach({}, async () => new Response("{}", { status: 429, headers: { "Retry-After": "7" } }));
  assert.ok(!said.ok && said.retryAfterS === 7);
});
