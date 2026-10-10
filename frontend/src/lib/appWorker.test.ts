// The page's side of the service worker (lib/appWorker.ts): registration, the update offer (never
// during a ride), Reload as the only way to skip waiting, and no reload the rider did not ask for.
import assert from "node:assert/strict";
import { test } from "node:test";
import { AppWorker, CHECK_EVERY_MS, SKIP_WAITING, UPDATE_READY, WORKER_URL, updateOffered, type Registration, type WaitingWorker, type WorkerContainer, type WorkerEnv } from "./appWorker.ts";
import { SKIP_WAITING as WORKER_SKIP_WAITING } from "../sw/swCore.mjs";

function fakeWorker(state = "installing") {
  const posted: unknown[] = [];
  const listeners: (() => void)[] = [];
  const worker: WaitingWorker & { posted: unknown[]; become(state: string): void } = {
    state,
    posted,
    postMessage: (m) => posted.push(m),
    addEventListener: (_type, fn) => listeners.push(fn),
    become(next) {
      worker.state = next;
      listeners.forEach((fn) => fn());
    },
  };
  return worker;
}

function fakeEnv({ controlled = true, waiting = null as WaitingWorker | null, enabled = true, refuse = false } = {}) {
  const found: (() => void)[] = [];
  const changed: (() => void)[] = [];
  const log: string[] = [];
  let now = 1_000_000;
  const registration: Registration & { fire(installing: WaitingWorker): void } = {
    waiting,
    installing: null,
    update: async () => void log.push("update"),
    addEventListener: (_type, fn) => found.push(fn),
    fire(installing) {
      registration.installing = installing;
      found.forEach((fn) => fn());
    },
  };
  const container: WorkerContainer = {
    controller: controlled ? {} : null,
    register: async (url, options) => {
      log.push(`register ${url} ${options.scope} ${options.updateViaCache}`);
      if (refuse) throw new Error("SecurityError");
      return registration;
    },
    addEventListener: (_type, fn) => changed.push(fn),
  };
  const env: WorkerEnv = { container, enabled, reload: () => log.push("reload"), now: () => now };
  return {
    env,
    log,
    registration,
    container,
    controllerChange: () => changed.forEach((fn) => fn()),
    advance: (ms: number) => (now += ms),
  };
}

test("the page and the worker agree on the message that skips waiting", () => {
  assert.equal(SKIP_WAITING, WORKER_SKIP_WAITING);
});

test("the offer shows when a version is waiting, and never during a ride", () => {
  assert.equal(updateOffered(true, false), true);
  assert.equal(updateOffered(true, true), false);
  assert.equal(updateOffered(false, false), false);
  assert.equal(UPDATE_READY, "A new version of RouteMaker is ready.");
});

test("registers /sw.js at scope / past the HTTP cache; not in dev, not without workers, and a refusal is quiet", async () => {
  const on = fakeEnv();
  assert.equal(await new AppWorker(on.env, () => undefined).start(), true);
  assert.deepEqual(on.log, [`register ${WORKER_URL} / none`]);
  const dev = fakeEnv({ enabled: false });
  assert.equal(await new AppWorker(dev.env, () => undefined).start(), false);
  assert.deepEqual(dev.log, []);
  const none = fakeEnv();
  assert.equal(await new AppWorker({ ...none.env, container: undefined }, () => undefined).start(), false);
  const refused = fakeEnv({ refuse: true });
  assert.equal(await new AppWorker(refused.env, () => undefined).start(), false);
});

test("a worker already waiting at load is offered", async () => {
  const ready: boolean[] = [];
  const env = fakeEnv({ waiting: fakeWorker("installed") });
  await new AppWorker(env.env, (r) => ready.push(r)).start();
  assert.deepEqual(ready, [true]);
});

test("a new version found later is offered once it has installed; a first install (no controller) is not", async () => {
  const ready: boolean[] = [];
  const env = fakeEnv();
  await new AppWorker(env.env, (r) => ready.push(r)).start();
  const installing = fakeWorker();
  env.registration.fire(installing);
  assert.deepEqual(ready, []);
  installing.become("installed");
  assert.deepEqual(ready, [true]);

  const first: boolean[] = [];
  const fresh = fakeEnv({ controlled: false });
  await new AppWorker(fresh.env, (r) => first.push(r)).start();
  const own = fakeWorker();
  fresh.registration.fire(own);
  own.become("installed");
  own.become("activated");
  assert.deepEqual(first, []);
});

test("Reload sends SKIP_WAITING to the waiting worker, and the page reloads once when it takes over", async () => {
  const waiting = fakeWorker("installed");
  const env = fakeEnv({ waiting });
  const worker = new AppWorker(env.env, () => undefined);
  await worker.start();
  worker.apply();
  assert.deepEqual(waiting.posted, [{ type: SKIP_WAITING }]);
  assert.ok(!env.log.includes("reload"), "not before the new worker controls the page");
  env.controllerChange();
  env.controllerChange();
  assert.equal(env.log.filter((l) => l === "reload").length, 1);
});

test("a controller change the rider did not ask for (a first install's claim, another tab's Reload) never reloads the page", async () => {
  const env = fakeEnv({ waiting: fakeWorker("installed") });
  await new AppWorker(env.env, () => undefined).start();
  env.controllerChange();
  assert.ok(!env.log.includes("reload"));
});

test("Reload with nothing waiting any more (another tab took it) is a plain reload", async () => {
  const env = fakeEnv();
  const worker = new AppWorker(env.env, () => undefined);
  await worker.start();
  worker.apply();
  assert.deepEqual(env.log.slice(-1), ["reload"]);
});

test("coming back to the front checks for a new version at most once an hour", async () => {
  const env = fakeEnv();
  const worker = new AppWorker(env.env, () => undefined);
  worker.check();
  assert.ok(!env.log.includes("update"), "nothing registered yet");
  await worker.start();
  worker.check();
  assert.ok(!env.log.includes("update"), "just registered");
  env.advance(CHECK_EVERY_MS);
  worker.check();
  worker.check();
  assert.equal(env.log.filter((l) => l === "update").length, 1);
});
