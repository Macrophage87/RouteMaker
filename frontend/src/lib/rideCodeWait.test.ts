// Start or Resume pressed before Ride mode's code is in (lib/rideCodeWait.ts): busy and "Opening Ride…" while it
// waits, one wait at a time, the press carried on once in, the rider told where it cannot come.
import { test } from "node:test";
import assert from "node:assert/strict";
import { OPENING_RIDE, rideCodeWaiter } from "./rideCodeWait.ts";

function setup() {
  const said: string[] = [];
  const busy: Array<string | null> = [];
  let settle: { ok: () => void; fail: () => void } | null = null;
  const wait = rideCodeWaiter<string>(
    () => new Promise<void>((ok, fail) => (settle = { ok, fail: () => fail(new Error("offline")) })),
    { waiting: (which) => busy.push(which), announce: (text) => said.push(text), failed: "No signal." },
  );
  return { said, busy, wait, settle: () => settle! };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

test("waiting: the pressed button busy and Opening Ride said; a second press ignored; the press carries on once in", async () => {
  const { said, busy, wait, settle } = setup();
  let went = 0;
  wait("start", () => went++);
  assert.deepEqual(busy, ["start"]);
  assert.deepEqual(said, [OPENING_RIDE]);
  assert.equal(OPENING_RIDE, "Opening Ride…");
  wait("resume", () => went++);
  assert.deepEqual(busy, ["start"], "a second press while waiting is ignored");
  settle().ok();
  await tick();
  assert.deepEqual(busy, ["start", null], "busy cleared");
  assert.equal(went, 1);
});

test("the code cannot come: busy cleared, the rider told, and a later press waits again", async () => {
  const { said, busy, wait, settle } = setup();
  let went = 0;
  wait("resume", () => went++);
  settle().fail();
  await tick();
  assert.deepEqual(busy, ["resume", null]);
  assert.deepEqual(said, [OPENING_RIDE, "No signal."]);
  assert.equal(went, 0);
  wait("resume", () => went++);
  assert.deepEqual(busy, ["resume", null, "resume"]);
});
