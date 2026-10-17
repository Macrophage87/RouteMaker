import { test } from "node:test";
import assert from "node:assert/strict";
import type { CapacitorBridge } from "./nativeShell.ts";
import {
  FILES_PLUGIN,
  FIT_TYPE,
  SEND_CANCELLED,
  SEND_FAILED,
  SENT_CHOOSER,
  SENT_GARMIN,
  SENT_SAVED,
  SENT_SAVED_COMPUTER,
  canSendToGarmin,
  SENT_SHARE,
  courseTrimmed,
  sendCourse,
  toBase64,
  type SendEnv,
} from "./sendToGarmin.ts";

const BYTES = new Uint8Array([14, 16, 0x6c, 0x08, 0xff, 0x00, 0x2e, 0x46, 0x49, 0x54]);
const NAME = "routemaker-default-1_9mi.fit";

function bridge(available: boolean, call?: (plugin: string, method: string, options?: Record<string, unknown>) => Promise<unknown>) {
  const calls: unknown[][] = [];
  const b: CapacitorBridge = {
    isNativePlatform: () => true,
    isPluginAvailable: (name) => available && name === FILES_PLUGIN,
    nativePromise: (plugin, method, options) => {
      calls.push([plugin, method, options]);
      return call ? call(plugin, method, options) : Promise.resolve({});
    },
    nativeCallback: () => "",
  };
  return { b, calls };
}

function saver() {
  const saved: [Uint8Array, string, string][] = [];
  return { saved, save: (bytes: Uint8Array<ArrayBuffer>, type: string, name: string) => void saved.push([bytes, type, name]) };
}

test("toBase64: the bytes as the bridge carries them, past one chunk too", () => {
  assert.equal(toBase64(BYTES), Buffer.from(BYTES).toString("base64"));
  const big = new Uint8Array(100_000).map((_, i) => i % 251);
  assert.equal(toBase64(big), Buffer.from(big).toString("base64"));
});

test("in the phone app: the file goes to the plugin, and nothing is saved or shared", async () => {
  const { b, calls } = bridge(true, async () => ({ app: "garmin-connect" }));
  const { saved, save } = saver();
  let shared = false;
  const env: SendEnv = { bridge: b, nav: { canShare: () => true, share: async () => void (shared = true) }, save, phone: true };
  assert.equal(await sendCourse(BYTES, NAME, env), SENT_GARMIN);
  assert.deepEqual(calls, [[FILES_PLUGIN, "openWith", { name: NAME, data: toBase64(BYTES) }]]);
  assert.equal(saved.length, 0);
  assert.equal(shared, false);
});

test("in the phone app without Garmin Connect taking it: the phone's list, and the line says what to pick", async () => {
  for (const answer of [{ app: "chooser" }, {}, null]) {
    const { b } = bridge(true, async () => answer);
    assert.equal(await sendCourse(BYTES, NAME, { bridge: b, nav: undefined, save: saver().save, phone: true }), SENT_CHOOSER);
  }
});

test("in the phone app: a refusal is said, not hidden", async () => {
  const { b } = bridge(true, () => Promise.reject(new Error("no")));
  assert.equal(await sendCourse(BYTES, NAME, { bridge: b, nav: undefined, save: saver().save, phone: true }), SEND_FAILED);
});

test("canSendToGarmin: a browser, or the app with the plugin; never an app from before it (a WebView can't hand a file on)", () => {
  assert.equal(canSendToGarmin(null), true);
  assert.equal(canSendToGarmin(bridge(true).b), true);
  assert.equal(canSendToGarmin(bridge(false).b), false);
  const old: CapacitorBridge = { ...bridge(true).b, isPluginAvailable: undefined };
  assert.equal(canSendToGarmin(old), false);
});

test("a browser that can share the file: the share sheet, with the FIT file", async () => {
  let got: File[] = [];
  const { saved, save } = saver();
  const env: SendEnv = { bridge: null, nav: { canShare: () => true, share: async ({ files }) => void (got = files) }, save, phone: true };
  assert.equal(await sendCourse(BYTES, NAME, env), SENT_SHARE);
  assert.equal(got.length, 1);
  assert.equal(got[0].name, NAME);
  assert.equal(got[0].type, FIT_TYPE);
  assert.deepEqual(new Uint8Array(await got[0].arrayBuffer()), BYTES);
  assert.equal(saved.length, 0);
});

test("the share sheet closed: not sent, and nothing saved", async () => {
  const { saved, save } = saver();
  const abort = Object.assign(new Error("closed"), { name: "AbortError" });
  const env: SendEnv = { bridge: null, nav: { canShare: () => true, share: () => Promise.reject(abort) }, save, phone: true };
  assert.equal(await sendCourse(BYTES, NAME, env), SEND_CANCELLED);
  assert.equal(saved.length, 0);
});

test("a browser that cannot share a .fit (Chrome on Android), or refuses: the file is saved and the line says what next", async () => {
  for (const nav of [undefined, { canShare: () => false, share: async () => {} }, { canShare: () => true, share: () => Promise.reject(new Error("NotAllowedError")) }]) {
    const { saved, save } = saver();
    assert.equal(await sendCourse(BYTES, NAME, { bridge: null, nav, save, phone: true }), SENT_SAVED);
    assert.deepEqual(saved, [[BYTES, FIT_TYPE, NAME]]);
  }
});

test("on a computer the saved file goes to Garmin Connect's website (there is no desktop app)", async () => {
  const { saved, save } = saver();
  assert.equal(await sendCourse(BYTES, NAME, { bridge: null, nav: undefined, save, phone: false }), SENT_SAVED_COMPUTER);
  assert.equal(saved.length, 1);
});

test("courseTrimmed: only when fitting left something out", () => {
  const profile = { maxBytes: 4_000_000 };
  const trim = { protectedOver: false, cuesBefore: 10, cuesKept: 10, pointsBefore: 500, pointsKept: 500, bytes: 9_000, profile };
  const as = (t: object) => ({ trim: { ...trim, ...t } }) as unknown as Parameters<typeof courseTrimmed>[0];
  assert.equal(courseTrimmed(as({})), false);
  assert.equal(courseTrimmed(as({ cuesKept: 9 })), true);
  assert.equal(courseTrimmed(as({ pointsKept: 400 })), true);
  assert.equal(courseTrimmed(as({ protectedOver: true })), true);
  assert.equal(courseTrimmed(as({ bytes: 5_000_000 })), true);
});
