// The compatibility layer for a site older than v0.8.0 (android/app/src/main/assets/routemaker-compat.js),
// run in a stand-in page: it uses the native plugins only inside the shell and only for a site without
// its own bridge; otherwise every browser API is the browser's own.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = (path) => fileURLToPath(new URL(path, import.meta.url));
const SCRIPT = readFileSync(here("../android/app/src/main/assets/routemaker-compat.js"), "utf8");
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function page({ wakeLock = false } = {}) {
  const log = [];
  class Document {}
  let realState = "visible";
  Object.defineProperty(Document.prototype, "visibilityState", { configurable: true, get: () => realState });
  Object.defineProperty(Document.prototype, "hidden", { configurable: true, get: () => realState === "hidden" });
  const document = new Document();
  const captures = [];
  class BrowserUtterance {
    constructor(text) {
      this.text = text;
      this.browser = true;
    }
  }
  const browserSynth = {
    speaking: false,
    speak: (u) => log.push(`web-speak:${u.text}`),
    cancel: () => log.push("web-cancel"),
    getVoices: () => ["v"],
  };
  const geolocation = {
    watchPosition: () => {
      log.push("web-watch");
      return 1;
    },
    clearWatch: (id) => log.push(`web-clear:${id}`),
    getCurrentPosition: () => log.push("web-current"),
  };
  const navigator = { geolocation };
  if (wakeLock) navigator.wakeLock = { request: () => Promise.resolve("real") };
  const window = {
    Document,
    document,
    navigator,
    SpeechSynthesisUtterance: BrowserUtterance,
    speechSynthesis: browserSynth,
    addEventListener: (type, fn, capture) => captures.push({ type, fn, capture }),
    Promise,
    Date,
  };
  window.window = window;
  vm.runInNewContext(SCRIPT, window);
  const callbacks = new Map();
  const pending = [];
  let ids = 0;
  const capacitor = {
    isNativePlatform: () => true,
    nativeCallback: (plugin, method, options, cb) => {
      ids += 1;
      log.push(`${plugin}.${method}`);
      callbacks.set(`cb${ids}`, cb);
      return `cb${ids}`;
    },
    nativePromise: (plugin, method, options) => {
      log.push(`${plugin}.${method}${options && options.text ? `:${options.text}` : options && options.id ? `:${options.id}` : ""}`);
      return new Promise((resolve) => pending.push(resolve));
    },
  };
  return {
    window,
    log,
    captures,
    pending,
    shell: () => void (window.Capacitor = capacitor),
    send: (id, data, error) => callbacks.get(id)?.(data, error),
    hide: () => void (realState = "hidden"),
  };
}

test("in a browser (no Capacitor): geolocation, speech and visibility are the browser's own", () => {
  const p = page();
  const { window, log } = p;
  assert.equal(window.navigator.geolocation.watchPosition(() => {}, () => {}, {}), 1);
  window.navigator.geolocation.clearWatch(1);
  const u = new window.SpeechSynthesisUtterance("Left now");
  assert.equal(u.browser, true);
  window.speechSynthesis.speak(u);
  assert.deepEqual(log, ["web-watch", "web-clear:1", "web-speak:Left now"]);
  p.hide();
  assert.equal(window.document.visibilityState, "hidden");
  assert.equal(window.navigator.wakeLock, undefined, "no stand-in lock outside the shell");
});

test("a v0.8.0 site (marked) in the shell: the layer stands aside", () => {
  const p = page();
  p.shell();
  p.window.__routemakerNativeShell = true;
  p.window.navigator.geolocation.watchPosition(() => {}, () => {});
  assert.equal(new p.window.SpeechSynthesisUtterance("x").browser, true);
  assert.deepEqual(p.log, ["web-watch"]);
  assert.match(readFileSync(here("../../frontend/src/lib/nativeShell.ts"), "utf8"), /export const BRIDGE_MARK = "__routemakerNativeShell";/);
});

test("an older site in the shell: the watch is native, fixes arrive as browser positions, End removes it", () => {
  const p = page();
  p.shell();
  const fixes = [];
  const fails = [];
  const geo = p.window.navigator.geolocation;
  const id = geo.watchPosition((pos) => fixes.push(pos), (e) => fails.push(e.code), { enableHighAccuracy: true });
  assert.deepEqual(p.log, ["BackgroundGeolocation.addWatcher"]);
  p.send("cb1", { latitude: 38.9, longitude: -77, accuracy: 5, speed: 4, bearing: 90, time: 7, altitude: null, altitudeAccuracy: null });
  assert.equal(fixes.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(fixes[0])), {
    coords: { latitude: 38.9, longitude: -77, accuracy: 5, altitude: null, altitudeAccuracy: null, heading: 90, speed: 4 },
    timestamp: 7,
  });
  p.send("cb1", undefined, { code: "NOT_AUTHORIZED" });
  p.send("cb1", undefined, { message: "off" });
  assert.deepEqual(fails, [1, 2]);
  // While riding, the page is told it is visible and never hears the change.
  p.hide();
  assert.equal(p.window.document.visibilityState, "visible");
  assert.equal(p.window.document.hidden, false);
  const capture = p.captures.find((c) => c.type === "visibilitychange");
  assert.equal(capture.capture, true);
  let stopped = false;
  capture.fn({ stopImmediatePropagation: () => (stopped = true) });
  assert.equal(stopped, true);
  geo.clearWatch(id);
  assert.equal(p.log.at(-1), "BackgroundGeolocation.removeWatcher:cb1");
  assert.equal(p.window.document.visibilityState, "hidden", "after End the real state again");
  stopped = false;
  capture.fn({ stopImmediatePropagation: () => (stopped = true) });
  assert.equal(stopped, false);
  p.send("cb1", { latitude: 1, longitude: 1, accuracy: 1 });
  assert.equal(fixes.length, 1, "nothing after End");
  geo.getCurrentPosition();
  assert.equal(p.log.at(-1), "web-current", "Use my location stays the WebView's own");
});

test("an older site in the shell: the voice is native; one at a time; a cancelled sentence never ends the next", async () => {
  const p = page();
  p.shell();
  const { window, log, pending } = p;
  const ended = [];
  const a = new window.SpeechSynthesisUtterance("In 500 feet, left");
  a.onend = () => ended.push("a");
  window.speechSynthesis.speak(a);
  assert.equal(window.speechSynthesis.speaking, true);
  window.speechSynthesis.cancel();
  assert.equal(window.speechSynthesis.speaking, false);
  const b = new window.SpeechSynthesisUtterance("Left now");
  b.onend = () => ended.push("b");
  window.speechSynthesis.speak(b);
  pending[0]();
  await flush();
  assert.deepEqual(ended, [], "a's late answer does not end b");
  pending.at(-1)();
  await flush();
  assert.deepEqual(ended, ["b"]);
  assert.deepEqual(log.filter((l) => l.startsWith("TextToSpeech")), ["TextToSpeech.speak:In 500 feet, left", "TextToSpeech.stop", "TextToSpeech.speak:Left now"]);
  assert.deepEqual(window.speechSynthesis.getVoices(), ["v"]);
});

test("the wake lock: a stand-in in the shell where the WebView has none; the real one left alone", async () => {
  const p = page();
  p.shell();
  const lock = await p.window.navigator.wakeLock.request("screen");
  assert.equal(lock.released, false);
  await lock.release();
  assert.equal(lock.released, true);
  const real = page({ wakeLock: true });
  real.shell();
  assert.equal(await real.window.navigator.wakeLock.request("screen"), "real");
});

test("the layer stores, logs and sends nothing", () => {
  const code = SCRIPT.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.doesNotMatch(code, /Storage|console\.|fetch\(|indexedDB|sendBeacon|XMLHttpRequest|WebSocket|postMessage|document\.cookie/);
});
